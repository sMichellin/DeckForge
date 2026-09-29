"""Обложка или финал из одного заголовка — пустое тело. Change `an-empty-body-is-an-error`,
план Б, круг 3, задача C3 (#245); нужна для замера A4.

Прогон `a3a8f3a2319b` (UI, WorkSpace): s01 и s10 — только заголовок на `ex014`. s10 называл
`integrity.content_lost` (план дал факты), s01 не называл никто: фактов обложке план не давал,
а `integrity.empty_slide` пропускал любой макет без места под тело как «титул по замыслу».
После #287 обложке и финалу строка помимо заголовка нужна всегда — по замыслу одним
заголовком бывает только раздел.

Сценарии — из дельты `openspec/changes/an-empty-body-is-an-error/specs/audit-deterministic/`.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from deckforge.audit.deterministic.integrity import empty_slide
from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import LayoutKind, TextRole
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline.replay import from_fixture
from tests.unit._audit_builders import context_for, deck

CHECK = "integrity.empty_slide"
WORKSPACE = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-29" / "workspace"


def _slide(*, recipe_id: str | None = None, body: str | None = None,
           layout_id: str = "L01") -> SlideIR:
    blocks = [TextBlock(block_id="b01", role=TextRole.TITLE, text="Автоматизация презентаций",
                        zone_id="zt" if recipe_id else None)]
    if body is not None:
        blocks.append(TextBlock(block_id="b02", role=TextRole.BODY, text=body,
                                zone_id="zb" if recipe_id else None))
    return SlideIR(slide_id="s01", layout_id=layout_id, variant="A", blocks=blocks,
                   recipe_id=recipe_id)


def _recipe(kind: RecipeKind) -> Recipe:
    return Recipe(recipe_id="ex014", example_index=1, kind=kind, zones=[
        Zone(zone_id="zt", xml_id=1, role=TypeLevel.SLIDE_TITLE, capacity_chars=40),
        Zone(zone_id="zb", xml_id=2, role=TypeLevel.BODY, capacity_chars=80),
    ])


def by_recipe(manifest: TemplateManifest, kind: RecipeKind, body: str | None = None) -> list:
    design = derive(manifest).model_copy(update={"recipes": [_recipe(kind)]})
    ctx = context_for(CHECK, deck(_slide(recipe_id="ex014", body=body)), manifest)
    return list(empty_slide(replace(ctx, design_system=design)))


def _with_kind(manifest: TemplateManifest, kind: LayoutKind) -> TemplateManifest:
    """Тот же манифест, у `L01` (место тела нулевое) — другой вид макета."""
    return manifest.model_copy(update={"layouts": [
        layout.model_copy(update={"kind": kind}) if layout.layout_id == "L01" else layout
        for layout in manifest.layouts
    ]})


def test_a_cover_by_recipe_with_only_a_title_is_empty(manifest: TemplateManifest) -> None:
    """Нарушитель: обложка по примеру — один заголовок, у макета места под тело нет."""
    findings = by_recipe(manifest, RecipeKind.COVER)

    assert [(f.slide_id, "Обложка" in f.message) for f in findings] == [("s01", True)]


def test_a_final_by_recipe_with_only_a_title_is_empty(manifest: TemplateManifest) -> None:
    """Нарушитель: финал — «что будет после» — одним заголовком не сказан."""
    assert [f.slide_id for f in by_recipe(manifest, RecipeKind.FINAL)] == ["s01"]


def test_a_closing_layout_with_only_a_title_is_empty(manifest: TemplateManifest) -> None:
    """Нарушитель без рецепта: вид макета «финал», на слайде только заголовок."""
    closing = _with_kind(manifest, LayoutKind.CLOSING)

    findings = list(empty_slide(context_for(CHECK, deck(_slide()), closing)))

    assert [f.slide_id for f in findings] == ["s01"]


def test_a_section_with_only_a_title_is_whole(manifest: TemplateManifest) -> None:
    """Норма: раздел из одного заголовка — строка между частями колоды, по замыслу."""
    assert by_recipe(manifest, RecipeKind.SECTION) == []
    section = _with_kind(manifest, LayoutKind.SECTION)
    assert list(empty_slide(context_for(CHECK, deck(_slide()), section))) == []


def test_a_cover_with_its_line_is_whole(manifest: TemplateManifest) -> None:
    """Норма: обложка с заголовком и строкой о колоде."""
    assert by_recipe(manifest, RecipeKind.COVER, body="Отчёт для правления, сентябрь") == []


def test_the_cover_of_run_a3a8f3a2319b_is_found() -> None:
    """Мерило C3: s01 прогона `a3a8f3a2319b` — обложка на `ex014` (макет `L09`), один
    заголовок. Колода собрана заново из того, что назвал `run.json` прогона
    (`slide_choices`), на манифесте и каталоге того же шаблона WorkSpace (фикстура 29.09)."""
    if not WORKSPACE.is_dir():
        pytest.skip("нет фикстуры WorkSpace 29.09")
    run = from_fixture(WORKSPACE)
    if run.manifest.layout("L09") is None:
        pytest.skip("в манифесте фикстуры нет макета L09")
    cover = SlideIR(slide_id="s01", layout_id="L09", variant="A", recipe_id="ex014", blocks=[
        TextBlock(block_id="b01", role=TextRole.TITLE, text="Автоматизация презентаций",
                  zone_id="z672"),
    ])
    ctx = context_for(CHECK, deck(cover), run.manifest)

    findings = list(empty_slide(replace(ctx, design_system=run.design_system)))

    assert [f.slide_id for f in findings] == ["s01"]
