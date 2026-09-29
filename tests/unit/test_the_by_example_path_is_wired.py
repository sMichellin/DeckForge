"""Путь `by_example` донесён по графу. Change `the-by-example-path-is-wired` (план Б, 3 + 5б).

Механизм пути есть в каждом слое: композиция под места (#261), слайд без примера без потерь
(#259). Граф же его не доносил: `compose` не передавал назначение, `fit`, `render` и `export`
не знали пути, а старт отказывал. Здесь сторожатся швы графа — без модели и без стенда:
композитор подменён, а вписывание и писатель настоящие.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, ClassVar

import pytest
from langgraph.runtime import Runtime

from deckforge.composition.assign import RecipeAssignment
from deckforge.config import RunConfig
from deckforge.designsystem.models import PlaceKind, TypeLevel
from deckforge.domain.content import Brief
from deckforge.domain.enums import SmartArtPattern
from deckforge.domain.slide import BulletsBlock, DeckIR, SlideIR, SmartArtBlock
from deckforge.export.pptx import export_pptx
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import compose as compose_module
from deckforge.pipeline.nodes.assign import assign_node
from deckforge.pipeline.nodes.compose import _bands_of_assigned_places, compose_node
from deckforge.pipeline.nodes.fit import _fit_shortening
from deckforge.pipeline.replay import from_fixture
from deckforge.registry.variants import load_variant_profiles
from tests.unit.test_no_example_goes_by_design import (
    blocks,
    content,
    slide_for,
    template_and_manifest,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-28" / "vk-tech"


# --- compose: назначение, шрифты, полоса заголовка ------------------------------------------


@pytest.fixture(scope="module")
def assigned(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """План VK Tech 28.09 после узла `assign`: дизайн-система с паспортами и назначения."""
    run = from_fixture(FIXTURE)
    deps = Deps(
        brief=Brief(purpose="report", audience="правление"), run=RunConfig(),
        out_dir=tmp_path_factory.mktemp("out"), fonts=FontLibrary.default(),
    )
    state = {
        "plan": run.plan, "manifest": run.manifest, "design_system": run.design_system,
        "seed": 1341, "composition_path": "by_example",
    }
    out = asyncio.run(assign_node(state, Runtime(context=deps)))  # type: ignore[arg-type]
    return {"run": run, "deps": deps, **out}


class _Composer:
    """Композитор-подделка: запоминает, с чем его собрали и о чём спросили."""

    made: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, client: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.asked: dict[str, Any] = {}
        self.notes: list[str] = []
        self.choices: dict[str, Any] = {}
        _Composer.made.append({"init": kwargs, "asked": self.asked})

    async def compose(self, slide: Any, *args: Any, **kwargs: Any) -> SlideIR:
        self.asked[slide.slide_id] = kwargs.get("assignment")
        return SlideIR(slide_id=slide.slide_id, layout_id="L01", variant="A", blocks=[])


class _Rewriter:
    """Переписчик заголовков-подделка: запоминает полосы и возвращает план как есть."""

    bands: ClassVar[dict[str, Any]] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.notes: list[str] = []

    async def rewrite_for_layouts(self, plan: Any, content: Any, *, bands: Any, seed: int) -> Any:
        _Rewriter.bands = dict(bands)
        return plan


def _compose(assigned: dict[str, Any], monkeypatch: pytest.MonkeyPatch, *,
             with_assignments: bool) -> dict[str, Any]:
    monkeypatch.setattr(compose_module, "SlideComposer", _Composer)
    monkeypatch.setattr(compose_module, "HeadlineRewriter", _Rewriter)
    _Composer.made.clear()
    run = assigned["run"]
    deps = assigned["deps"]
    deps.llm = object()
    state: dict[str, Any] = {
        "plan": run.plan, "content": run.content, "manifest": run.manifest,
        "variant": load_variant_profiles()["A"], "seed": 1341,
        "design_system": assigned["design_system"],
    }
    if with_assignments:
        state["assignments"] = assigned["assignments"]
    asyncio.run(compose_node(state, Runtime(context=deps)))  # type: ignore[arg-type]
    (made,) = _Composer.made
    return made


def test_compose_hands_the_assignment_and_the_fonts_to_the_composer(
    assigned: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Норма: каждый слайд получает своё назначение, композитор — шрифты шаблона."""
    made = _compose(assigned, monkeypatch, with_assignments=True)

    assert made["init"]["fonts"] is assigned["deps"].fonts
    assert made["asked"] == {a.slide_id: a for a in assigned["assignments"]}


def test_on_legacy_the_composer_gets_no_assignment(
    assigned: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Нарушитель: без назначений в состоянии (`legacy`) слайд идёт прежним путём."""
    made = _compose(assigned, monkeypatch, with_assignments=False)

    assert set(made["asked"].values()) == {None}


def test_the_headline_band_is_the_title_place_of_the_example(assigned: dict[str, Any]) -> None:
    """Норма: полоса заголовка слайда с примером — предел места заголовка его паспорта."""
    recipes = {r.recipe_id: r for r in assigned["design_system"].recipes}
    by_slide = {a.slide_id: a for a in assigned["assignments"]}
    bands = _bands_of_assigned_places(
        by_slide, assigned["run"].manifest, assigned["design_system"], assigned["deps"].fonts
    )

    assert bands
    for slide_id, band in bands.items():
        passport = recipes[by_slide[slide_id].recipe_id].passport  # type: ignore[index]
        title = next(p for p in passport.places
                     if p.role is TypeLevel.SLIDE_TITLE and p.kind is PlaceKind.TEXT)
        assert band.limit == title.capacity_chars
        assert band.fits("Итоги")


def test_a_slide_without_an_example_keeps_the_layout_band(assigned: dict[str, Any]) -> None:
    """Нарушитель: слайду без примера полоса места не выдумывается — остаётся полоса макета."""
    empty = {"s99": RecipeAssignment(slide_id="s99", recipe_id=None, reason="примера нет")}

    assert _bands_of_assigned_places(
        empty, assigned["run"].manifest, assigned["design_system"], assigned["deps"].fonts
    ) == {}


# --- fit, render: слайд без примера не сплющивается ------------------------------------------


def _fitted(tmp_path: Path, block_id: str, *, by_example: bool) -> tuple[SlideIR, list[str]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    _, manifest, fonts = template_and_manifest(tmp_path)
    block = next(b for b in blocks(manifest) if b.block_id == block_id)
    slide = slide_for(
        RecipeAssignment(slide_id="s01", recipe_id=None, reason="примера нет"), block, manifest
    )
    return _fit_shortening(slide, manifest, fonts, content(), by_example=by_example)


def test_a_long_scheme_without_an_example_stays_a_scheme_on_by_example(tmp_path: Path) -> None:
    """Норма: узел `fit` на пути `by_example` не сплющивает длинную схему — она с замером."""
    slide, notes = _fitted(tmp_path, "sa-long", by_example=True)

    (scheme,) = [b for b in slide.blocks if b.block_id == "sa-long"]
    assert isinstance(scheme, SmartArtBlock)
    assert "sa-long" in slide.fit_report
    assert not any("записана списком" in note for note in notes)


def test_on_legacy_the_long_scheme_is_still_a_list(tmp_path: Path) -> None:
    """Нарушитель: без пути `by_example` узел `fit` сплющивает её, как раньше."""
    slide, notes = _fitted(tmp_path, "sa-long", by_example=False)

    (scheme,) = [b for b in slide.blocks if b.block_id == "sa-long"]
    assert isinstance(scheme, BulletsBlock)
    assert any("записана списком" in note for note in notes)


def test_a_hierarchy_is_measured_only_on_by_example(tmp_path: Path) -> None:
    """Норма и нарушитель: замер иерархии есть только на пути `by_example` — без него писатель
    этого пути отказал бы («нет замера вписывания»)."""
    wired, _ = _fitted(tmp_path / "a", "sa-hierarchy", by_example=True)
    legacy, _ = _fitted(tmp_path / "b", "sa-hierarchy", by_example=False)

    assert "sa-hierarchy" in wired.fit_report
    assert "sa-hierarchy" not in legacy.fit_report


def test_fit_and_export_on_by_example_write_the_scheme(tmp_path: Path) -> None:
    """Норма: вписывание и `export_pptx` одного пути — схема записана без отказа писателя."""
    template, manifest, fonts = template_and_manifest(tmp_path)
    block = next(b for b in blocks(manifest) if b.block_id == "sa-hierarchy")
    slide = slide_for(
        RecipeAssignment(slide_id="s01", recipe_id=None, reason="примера нет"), block, manifest
    )
    fitted, _ = _fit_shortening(slide, manifest, fonts, content(), by_example=True)
    deck = DeckIR(deck_id="d1", variant="A", template_id=manifest.template_id, seed=7,
                  slides=[fitted])

    out = export_pptx(deck, manifest, template, tmp_path / "deck.pptx", content=content(),
                      fonts=fonts, by_example=True)

    assert out.is_file()
    assert block.pattern is SmartArtPattern.HIERARCHY


def test_the_plan_b_profile_differs_from_the_base_only_by_the_path() -> None:
    """Норма: профиль `plan_b` — база прогонов 28.09 с путём `by_example`, и больше ничем.

    Иначе приёмка сравнила бы не пути, а два разных конфига."""
    from deckforge.config import load_run_config

    base = load_run_config().model_dump()
    plan_b = load_run_config(profile="plan_b").model_dump()

    assert plan_b["composition"]["path"] == "by_example"
    assert {k: v for k, v in plan_b.items() if k != "composition"} == {
        k: v for k, v in base.items() if k != "composition"
    }
