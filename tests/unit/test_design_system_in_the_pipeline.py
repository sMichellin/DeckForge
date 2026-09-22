"""DG2 `design-system-in-the-pipeline`: дизайн-система считается узлом `parse`.

Слой `designsystem` проверяется своими тестами (`tests/unit/designsystem/`). Здесь —
только шов: узел кладёт в состояние ДС того же манифеста, считает её и на манифесте
из кэша, а сводка прогона называет числа её разделов.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.runtime import Runtime

from deckforge.config import RunConfig
from deckforge.designsystem import DesignSystem, derive
from deckforge.domain.content import Brief
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import parse as parse_module
from deckforge.pipeline.run import RunResult, design_system_summary
from deckforge.pipeline.state import DeckState


def _deps(tmp_path: Path) -> Deps:
    brief = Brief(purpose="product", audience="правление", target_slides=6, language="ru")
    return Deps(brief=brief, run=RunConfig(), out_dir=tmp_path)


class _Classifier:
    """Классификатор без модели: предел не исчерпан, откатов нет."""

    overdue = False
    fell_back = 0

    def __init__(self, *_: Any, **__: Any) -> None:
        pass


def _stub_parser(monkeypatch: pytest.MonkeyPatch, manifest: TemplateManifest) -> list[int]:
    """Парсер отдаёт готовый манифест — как кэш; счётчик — сколько раз его звали."""
    calls: list[int] = []

    def parse(*_a: Any, **_k: Any) -> TemplateManifest:
        calls.append(1)
        return manifest

    monkeypatch.setattr(parse_module, "LayoutClassifier", _Classifier)
    monkeypatch.setattr(
        parse_module, "TemplateParser", lambda **_: SimpleNamespace(parse=parse)
    )
    return calls


def _derive_counter(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Обёртка над настоящей `derive`: считает вызовы, не подменяя результат."""
    seen: list[str] = []

    def counted(manifest: TemplateManifest) -> DesignSystem:
        seen.append(manifest.template_id)
        return derive(manifest)

    monkeypatch.setattr(parse_module, "derive", counted)
    return seen


async def test_parse_puts_the_design_system_of_the_same_manifest_into_the_state(
    tmp_path: Path, manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Норма: после `parse` ДС в состоянии, и она ровно та, что `derive` даёт манифесту."""
    _stub_parser(monkeypatch, manifest)
    state: DeckState = {"template_path": tmp_path / "t.pptx", "seed": 1}

    out = await parse_module.parse_node(state, Runtime(context=_deps(tmp_path)))

    assert out["manifest"] is manifest
    ds = out["design_system"]
    assert isinstance(ds, DesignSystem)
    assert ds.template_id == manifest.template_id
    assert ds == derive(manifest)
    # Замер стадии прежний: отдельной стадии под ДС нет, бюджет §12 не меняется.
    assert set(out["stage_timings_s"]) == {"parse_template"}


async def test_the_design_system_is_recomputed_when_the_manifest_comes_from_cache(
    tmp_path: Path, manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Кэшируется манифест, а не производные: каждый прогон считает ДС заново."""
    parsed = _stub_parser(monkeypatch, manifest)
    derived = _derive_counter(monkeypatch)
    state: DeckState = {"template_path": tmp_path / "t.pptx", "seed": 1}

    first = await parse_module.parse_node(state, Runtime(context=_deps(tmp_path)))
    second = await parse_module.parse_node(state, Runtime(context=_deps(tmp_path)))

    assert len(parsed) == 2
    assert derived == [manifest.template_id, manifest.template_id]
    assert first["design_system"] == second["design_system"]


async def test_a_failed_parse_leaves_no_design_system_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Нарушитель: без манифеста ДС не существует — узел падает, а не кладёт заготовку."""

    def broken(*_a: Any, **_k: Any) -> TemplateManifest:
        raise ValueError("битый пакет")

    derived = _derive_counter(monkeypatch)
    monkeypatch.setattr(parse_module, "LayoutClassifier", _Classifier)
    monkeypatch.setattr(
        parse_module, "TemplateParser", lambda **_: SimpleNamespace(parse=broken)
    )
    state: DeckState = {"template_path": tmp_path / "t.pptx", "seed": 1}

    with pytest.raises(ValueError, match="битый пакет"):
        await parse_module.parse_node(state, Runtime(context=_deps(tmp_path)))
    assert derived == []


def test_summary_counts_every_section_of_the_design_system(manifest: TemplateManifest) -> None:
    """Сводка — числа разделов, а не сами значения: по ним видно, что шаблон разобран."""
    ds = derive(manifest)

    summary = design_system_summary(ds)

    assert summary == {
        "template_id": manifest.template_id,
        "type_levels": len(ds.typography.steps),
        "theme_slots": len(ds.theme.slots),
        "spacing_steps": len(ds.grid.spacing.steps_emu),
        "color_roles": len(ds.palette_roles),
        "combinations": len(ds.combinations),
        "contrast_pairs": len(ds.contrast_pairs),
        "contrast_defects": len(ds.contrast_defects),
        "fonts_in_use": len(ds.fonts_in_use),
        "components": len(ds.components),
        "synthesized": len(ds.synthesized),
        "assembly_rules": len(ds.assembly_rules),
    }
    # Лестница и тема есть у любого шаблона — пустыми они были бы признаком заготовки.
    assert summary["type_levels"] > 0 and summary["theme_slots"] > 0


def test_run_report_names_the_design_system(
    tmp_path: Path, manifest: TemplateManifest
) -> None:
    """`run.json` получает раздел `design_system` — требование DG2."""
    ds = derive(manifest)
    state: DeckState = {"seed": 1, "manifest": manifest, "design_system": ds}
    result = RunResult(variant="A", run_id="r1", out_dir=tmp_path, state=state)

    report = result.report()

    assert report["design_system"] == design_system_summary(ds)


def test_run_report_says_so_when_parse_did_not_get_to_the_design_system(
    tmp_path: Path,
) -> None:
    """Нарушитель: прогон упал до `parse` — раздел есть и пуст, а не выдуман и не пропал."""
    result = RunResult(variant="A", run_id="r1", out_dir=tmp_path, state={"seed": 1})

    assert result.report()["design_system"] is None
