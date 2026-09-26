"""Почему слайд собран так — видно в отчёте прогона. Change `slide-choice-is-explained`, Т7
(`docs/agents/requirements-from-notes-26-09.md`).

Заметка 26.09: «Не понятен выбор слайдов под контент». Подборщик рецептов решал молча:
в `run.json` были только рецепты по слайдам (`design_system_usage`) и заметки об откатах,
а на вопрос «почему этот» ответа не было нигде.

Сценарии — из дельты `openspec/changes/slide-choice-is-explained/specs/slide-composition/`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deckforge.composition.composer import SlideComposer
from deckforge.composition.recipe_picker import pick_recipe, why_recipe
from deckforge.config import RunConfig
from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import TemplateManifest
from deckforge.inference.client import Completion
from deckforge.parsing import TemplateParser
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.run import collect_content_paths, generate_variant, load_brief
from deckforge.registry import load_variant_profiles
from tests.integration.test_native_objects import build_template
from tests.integration.test_pipeline_end_to_end import FakeInference, theme_fonts


def recipe(index: int, kind: RecipeKind, *, repeats: int = 0, picture: bool = False) -> Recipe:
    """Рецепт на три факта: три повтора, а без повторов — три свободные зоны тела.

    Меньше мест, чем фактов, — и рецепт не вмещающий (RG28): путь выбора был бы другим.
    """
    zones = [Zone(zone_id="z1", xml_id=1, role=TypeLevel.SLIDE_TITLE, capacity_chars=90)]
    zones += [
        Zone(
            zone_id=f"z{n}",
            xml_id=n,
            role=TypeLevel.BODY,
            repeat=(n - 2) if repeats else None,
            capacity_chars=200,
        )
        for n in range(2, 2 + max(repeats, 3))
    ]
    return Recipe(
        recipe_id=f"ex{index:03d}",
        example_index=index,
        kind=kind,
        repeats=repeats,
        zones=zones,
        has_picture=picture,
    )


def slide(intent: SlideIntent = SlideIntent.EVIDENCE, visual: str | None = None) -> SlidePlan:
    return SlidePlan(
        slide_id="s03",
        intent=intent,
        headline="Три причины выбрать платформу",
        fact_refs=["f001", "f002", "f003"],
        suggested_visual=visual,
    )


def explained(plan: SlidePlan, recipes: list[Recipe]) -> tuple[Recipe | None, dict[str, object]]:
    explain: dict[str, object] = {}
    chosen = pick_recipe(plan, recipes, explain=explain)
    return chosen, explain


# --- путь выбора ---------------------------------------------------------------------------


def test_the_kind_ordered_by_the_plan_is_named() -> None:
    chosen, explain = explained(
        slide(visual="cards"), [recipe(1, RecipeKind.TEXT), recipe(2, RecipeKind.CARDS, repeats=3)]
    )
    assert chosen is not None and chosen.kind is RecipeKind.CARDS
    assert explain["path"] == "named" and explain["wanted"] == "cards"
    assert "«cards» заказан планом" in why_recipe(explain, chosen)


def test_a_missing_kind_falls_back_and_says_so() -> None:
    chosen, explain = explained(slide(visual="kpi"), [recipe(1, RecipeKind.TEXT)])
    assert chosen is not None and explain["path"] == "fitting"
    assert why_recipe(explain, chosen).startswith("заказанного вида нет")


def test_a_recipe_with_too_few_places_is_named_as_the_roomiest() -> None:
    """Мест меньше, чем фактов, у всех рецептов (RG28): взят самый вместительный — и это сказано."""
    single = recipe(1, RecipeKind.TEXT).model_copy(
        update={"zones": recipe(1, RecipeKind.TEXT).zones[:1]}
    )
    chosen, explain = explained(slide(visual="cards"), [single])
    assert chosen is single and explain["path"] == "roomiest"
    assert "самый вместительный" in why_recipe(explain, chosen)


def test_a_structural_slide_names_its_own_or_related_kind() -> None:
    cover = recipe(1, RecipeKind.COVER)
    chosen, explain = explained(slide(SlideIntent.TITLE), [cover])
    assert chosen is cover and explain["path"] == "own"

    section = recipe(2, RecipeKind.SECTION)
    chosen, explain = explained(slide(SlideIntent.CLOSING), [section])
    assert chosen is section and explain["path"] == "related"
    assert "«final»" in why_recipe(explain, chosen) and "«section»" in why_recipe(explain, chosen)


def test_an_empty_catalogue_says_the_layout_is_used() -> None:
    chosen, explain = explained(slide(), [])
    assert chosen is None and explain["path"] == "empty"
    assert "по макету" in why_recipe(explain, chosen)


@pytest.mark.parametrize(
    "path", ["named", "own", "related", "plain", "fitting", "roomiest", "none", "empty"]
)
def test_every_path_has_a_phrase(path: str) -> None:
    phrase = why_recipe({"path": path, "wanted": "cards", "fitting": 2}, None)
    assert phrase and "{" not in phrase


# --- композитор и отчёт --------------------------------------------------------------------


class FakeLlm:
    model = "fake"

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        payload = {
            "blocks": [
                {
                    "block_id": "b1",
                    "type": "text",
                    "role": "title",
                    "text": "Три причины выбрать платформу",
                }
            ]
        }
        return Completion(text=json.dumps(payload, ensure_ascii=False), model=self.model)


async def test_the_composer_records_the_choice(manifest: TemplateManifest) -> None:
    design = derive(manifest).model_copy(update={"recipes": [recipe(1, RecipeKind.TEXT)]})
    content = ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=6),
        facts=[Fact(fact_id=f"f00{n}", text=f"Причина {n}") for n in (1, 2, 3)],
    )
    composer = SlideComposer(FakeLlm())

    await composer.compose(
        slide(visual="cards"),
        content,
        manifest,
        load_variant_profiles()["A"],
        seed=1,
        design_system=design,
    )

    choice = composer.choices["s03"]
    assert choice["recipe_id"] == "ex001" and choice["recipe_kind"] == "text"
    assert choice["visual"] == "cards" and choice["layout_id"]
    assert str(choice["why"]).startswith("заказанного вида нет")


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    content = tmp_path / "content"
    content.mkdir()
    (content / "факты.md").write_text(
        "# Итоги года\n\nВыручка выросла на 37,5 % за год.\n\nКлиентов стало более 500.\n",
        encoding="utf-8",
    )
    brief = tmp_path / "brief.yaml"
    brief.write_text(
        "purpose: product\naudience: правление\ntarget_slides: 6\nlanguage: ru\n",
        encoding="utf-8",
    )
    return {
        "template": build_template(tmp_path / "template.pptx"),
        "content": content,
        "brief": brief,
        "root": tmp_path,
    }


async def test_the_run_report_explains_every_slide(workspace: dict[str, Path]) -> None:
    """Нарушитель до правки: в `run.json` раздела нет вовсе."""
    root = workspace["root"]
    manifest = TemplateParser(cache_dir=root / "cache").parse(workspace["template"])
    out_dir = root / "out"
    deps = Deps(
        brief=load_brief(workspace["brief"]),
        run=RunConfig(exports=["pptx"], audit={"run_semantic": False, "auto_fix": False}),
        out_dir=out_dir,
        llm=FakeInference(manifest),
        fonts=theme_fonts(root, manifest),
        cache_dir=root / "cache",
        work_dir=out_dir,
    )
    result = await generate_variant(
        workspace["template"],
        collect_content_paths(workspace["content"]),
        load_variant_profiles()["A"],
        deps,
        seed=1337,
        run_id="choices",
    )

    report = json.loads(result.write_report().read_text(encoding="utf-8"))
    choices = report["slide_choices"]
    planned = [s.slide_id for s in result.state["plan"].slides]
    assert [c["slide_id"] for c in choices] == planned, "порядок — по плану"
    assert all(c["why"] and c["layout_id"] for c in choices)
