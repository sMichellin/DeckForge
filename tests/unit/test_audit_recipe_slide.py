"""Слайд по рецепту аудит меряет его рецептом, а не макетом из плана. Change
`recipe-slide-is-audited-by-its-zones`, таск RG27 (`docs/agents/tasks-25-09.md`).

Три колоды 24.09: 63 ошибки аудита, из них 43 — `template.layout_not_from_template` (27)
и `layout.text_overflow` (16) на слайдах по рецепту. Слайд по рецепту лежит на макете
**примера** (писатель берёт его макет), а текст стоит в зонах рецепта — линейка макета
из плана к нему не прикладывается.

Сценарии — из дельты `openspec/changes/recipe-slide-is-audited-by-its-zones/specs/`.
Правило 7 AGENTS.md: у обеих проверок нарушитель и норма.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from deckforge.audit.deterministic import template as template_checks
from deckforge.audit.deterministic.layout import text_overflow
from deckforge.audit.deterministic.template import layout_not_from_template
from deckforge.audit.recipes import catalogue, recipe_layout_part
from deckforge.designsystem import DesignSystem, derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.audit import Finding
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import FitResult, SlideIR, TextBlock
from deckforge.domain.template import TemplateExample, TemplateManifest
from tests.unit._audit_builders import context_for, deck, slide

EXAMPLE_LAYOUT = "ppt/slideLayouts/slideLayout13.xml"
PLAN_LAYOUT = "ppt/slideLayouts/slideLayout7.xml"
OTHER_LAYOUT = "ppt/slideLayouts/slideLayout2.xml"


@pytest.fixture
def with_example(manifest: TemplateManifest) -> TemplateManifest:
    """Манифест, где план выбирает `L07` (slideLayout7), а пример ex018 лежит на `L01`
    (slideLayout13): у синтетического манифеста обе части совпадали, и различить
    «план» и «пример» было бы нечем."""
    first, second = manifest.layouts[0], manifest.layouts[-1]
    layouts = [
        first.model_copy(update={"part_name": EXAMPLE_LAYOUT}),
        second.model_copy(update={"part_name": PLAN_LAYOUT}),
    ]
    example = TemplateExample(
        slide_index=18,
        layout_id=first.layout_id,
        part_name="ppt/slides/slide18.xml",
        shapes=[],
    )
    return manifest.model_copy(update={"layouts": layouts, "examples": [example]})


def recipe(
    *zones: Zone, part_name: str | None = "ppt/slides/slide18.xml", index: int = 18
) -> Recipe:
    return Recipe(
        recipe_id="ex018",
        example_index=index,
        part_name=part_name,
        kind=RecipeKind.TEXT,
        zones=list(zones) or [Zone(zone_id="z1", role=TypeLevel.SLIDE_TITLE, capacity_chars=90)],
    )


def design_with(manifest: TemplateManifest, *recipes: Recipe) -> DesignSystem:
    return derive(manifest).model_copy(update={"recipes": list(recipes)})


def recipe_slide(*blocks: TextBlock, fit: dict[str, FitResult] | None = None) -> SlideIR:
    """Слайд по рецепту ex018: план объявил `L07`, каждый текстовый блок в зоне."""
    return slide(*blocks, layout_id="L07").model_copy(
        update={"recipe_id": "ex018", "fit_report": fit or {}}
    )


def in_zone(text: str, zone_id: str = "z2", block_id: str = "b1") -> TextBlock:
    return TextBlock(block_id=block_id, role=TextRole.BODY, text=text, zone_id=zone_id)


def layout_findings(
    manifest: TemplateManifest,
    ir: SlideIR,
    design: DesignSystem,
    actual: str,
    monkeypatch: pytest.MonkeyPatch,
) -> list[Finding]:
    """Часть макета в файле подменяется: открывать настоящий pptx здесь незачем."""
    monkeypatch.setattr(template_checks, "_layout_parts_in_file", lambda ctx: [actual])
    ctx = replace(
        context_for("template.layout_not_from_template", deck(ir), manifest, deck_path=Path("x")),
        design_system=design,
    )
    # Сверка частей макета — находки с `actual`; прочие ветки проверки здесь не о том.
    return [finding for finding in layout_not_from_template(ctx) if "actual" in finding.evidence]


# --- layout_not_from_template ---------------------------------------------------------


def test_a_recipe_slide_on_the_layout_of_its_example_is_fine(
    with_example: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Норма. До правки — ложная ошибка: план объявлял slideLayout7."""
    ir = recipe_slide(in_zone("Текст", "z1"))
    design = design_with(with_example, recipe())

    assert layout_findings(with_example, ir, design, EXAMPLE_LAYOUT, monkeypatch) == []


def test_a_recipe_slide_on_a_foreign_layout_is_a_finding(
    with_example: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Нарушитель: писатель склонировал не тот пример."""
    ir = recipe_slide(in_zone("Текст", "z1"))
    design = design_with(with_example, recipe())

    found = layout_findings(with_example, ir, design, OTHER_LAYOUT, monkeypatch)

    assert len(found) == 1
    message = found[0].message
    assert "ex018" in message and OTHER_LAYOUT in message and EXAMPLE_LAYOUT in message
    assert found[0].evidence["expected"] == EXAMPLE_LAYOUT


def test_a_recipe_whose_example_layout_is_unknown_is_skipped(
    with_example: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    ir = recipe_slide(in_zone("Текст", "z1"))
    orphan = recipe(part_name=None, index=99)
    design = design_with(with_example, orphan)

    assert recipe_layout_part(orphan, with_example) is None
    assert layout_findings(with_example, ir, design, OTHER_LAYOUT, monkeypatch) == []


def test_a_slide_built_on_a_layout_keeps_the_old_check(
    with_example: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Слайд не по рецепту и не на том макете — находка, как и прежде."""
    ir = slide(TextBlock(block_id="b1", role=TextRole.BODY, text="Текст"), layout_id="L07")
    design = design_with(with_example, recipe())

    found = layout_findings(with_example, ir, design, OTHER_LAYOUT, monkeypatch)

    assert len(found) == 1
    assert found[0].evidence["actual"] == OTHER_LAYOUT
    assert "recipe_id" not in found[0].evidence


# --- text_overflow ----------------------------------------------------------------------


def overflow(manifest: TemplateManifest, ir: SlideIR, design: DesignSystem) -> list[Finding]:
    ctx = replace(context_for("layout.text_overflow", deck(ir), manifest), design_system=design)
    return list(text_overflow(ctx))


TEXT_42 = "Анализ шаблона и извлечение его структуры!"


def test_text_shorter_than_the_zone_is_fine(with_example: TemplateManifest) -> None:
    """Норма. До правки — ложная ошибка по вместимости макета, если та меньше."""
    assert len(TEXT_42) == 42
    design = design_with(
        with_example, recipe(Zone(zone_id="z2", role=TypeLevel.BODY, capacity_chars=60))
    )
    manifest = _tight_layout(with_example)

    assert overflow(manifest, recipe_slide(in_zone(TEXT_42)), design) == []


def test_text_longer_than_the_zone_names_the_zone(with_example: TemplateManifest) -> None:
    """Нарушитель: 42 знака в зоне на 32 — ошибка по зоне, а не по макету."""
    design = design_with(
        with_example, recipe(Zone(zone_id="z2", role=TypeLevel.BODY, capacity_chars=32))
    )

    found = overflow(with_example, recipe_slide(in_zone(TEXT_42)), design)

    assert len(found) == 1
    assert found[0].evidence["source"] == "zone_capacity"
    assert found[0].evidence["zone_id"] == "z2"
    assert "зоны z2" in found[0].message and "макета" not in found[0].message


def test_a_block_without_a_zone_is_measured_by_the_layout(with_example: TemplateManifest) -> None:
    ir = slide(TextBlock(block_id="b1", role=TextRole.BODY, text=TEXT_42), layout_id="L07")
    design = design_with(with_example, recipe())

    found = overflow(_tight_layout(with_example), ir, design)

    assert len(found) == 1 and found[0].evidence["source"] == "capacity"


def test_a_measurement_is_trusted_over_the_zone(with_example: TemplateManifest) -> None:
    """Вёрстка померила блок и он влез — вместимость зоны не пересчитывается."""
    design = design_with(
        with_example, recipe(Zone(zone_id="z2", role=TypeLevel.BODY, capacity_chars=10))
    )
    fit = {"b1": FitResult(final_size_pt=18.0, overflow=False)}

    assert overflow(with_example, recipe_slide(in_zone(TEXT_42), fit=fit), design) == []


# --- каталог ----------------------------------------------------------------------------


def test_without_a_design_system_the_catalogue_is_derived(manifest: TemplateManifest) -> None:
    """Вызов вне графа и старый чекпойнт: каталог — тем же `derive`, что у `parse`."""
    ctx = context_for("layout.text_overflow", deck(), manifest)

    assert ctx.design_system is None
    assert set(catalogue(ctx)) == {item.recipe_id for item in derive(manifest).recipes}


def _tight_layout(manifest: TemplateManifest) -> TemplateManifest:
    """Макет плана с вместимостью тела 32: ложная ошибка до правки видна на 42 знаках."""
    layouts = [
        layout.model_copy(
            update={"capacity": layout.capacity.model_copy(update={"max_chars_body": 32})}
        )
        if layout.layout_id == "L07"
        else layout
        for layout in manifest.layouts
    ]
    return manifest.model_copy(update={"layouts": layouts})
