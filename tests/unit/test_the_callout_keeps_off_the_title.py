"""Свободный блок не встаёт над заголовком. Change `the-callout-keeps-off-the-title`.

План Б, круг 2, корень К5. Сценарии — из дельты
`openspec/changes/the-callout-keeps-off-the-title/specs/slide-composition/`.

На прогоне 29.09 Education s02 получил выноску, а s08 — схему **над** заголовком слайда:
между верхом области контента и рамкой заголовка у шаблона щель в 5,2 мм во всю ширину,
и решатель честно считал её свободным местом.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.composition.composer import SlideComposer
from deckforge.domain.base import BBox
from deckforge.domain.enums import CalloutTone, TextRole
from deckforge.domain.slide import BulletItem, BulletsBlock, CalloutBlock, TextBlock
from deckforge.domain.template import (
    LayoutCapacity,
    LayoutKind,
    LayoutSpec,
    PlaceholderSpec,
    TemplateManifest,
)
from deckforge.layout.by_design import DesignRules
from deckforge.pipeline.replay import from_fixture

CM = 360_000
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-29"


def composer() -> SlideComposer:
    """Композитор без модели: проверяется размещение, а не текст."""
    made = SlideComposer.__new__(SlideComposer)
    made.notes = []
    return made


def layout_with(title: PlaceholderSpec, *rest: PlaceholderSpec) -> LayoutSpec:
    return LayoutSpec(
        layout_id="L22", name="Заголовок и текст", master="M01",
        part_name="ppt/slideLayouts/slideLayout1.xml", index=1, kind=LayoutKind.BULLETS,
        kind_confidence=0.9, kind_source="heuristic",
        capacity=LayoutCapacity(max_bullets=6, max_chars_body=420, max_chars_title=90),
        placeholders=[title, *rest],
    )


def title_band(layout: LayoutSpec, manifest: TemplateManifest) -> BBox:
    """Полоса заголовка: от верха области контента до низа его рамки, по её ширине."""
    box = layout.placeholders[0].bbox
    content = manifest.content_bbox
    return BBox(x=box.x, y=content.y, cx=box.cx, cy=box.bottom - content.y)


def blocks_of() -> list:
    return [
        TextBlock(block_id="b01", role=TextRole.TITLE, text="Вывод слайда", placeholder_idx=0),
        CalloutBlock(
            block_id="b02", text="Ручная адаптация шаблонов съедает день",
            tone=CalloutTone.RISK,
        ),
    ]


def place(manifest: TemplateManifest, layout: LayoutSpec, blocks: list) -> list:
    return composer()._place_free(
        blocks, ["b02"], layout, manifest, "s02", DesignRules(manifest)
    )


def test_a_free_block_stays_out_of_the_strip_above_the_title(
    manifest: TemplateManifest,
) -> None:
    """Нарушитель: щель над заголовком во всю ширину — не место для выноски."""
    title = PlaceholderSpec(
        idx=0, ph_type="TITLE", role=TextRole.TITLE,
        x=2 * CM, y=2 * CM, cx=29 * CM, cy=2 * CM,
    )
    body = PlaceholderSpec(
        idx=1, ph_type="BODY", role=TextRole.BODY,
        x=2 * CM, y=5 * CM, cx=29 * CM, cy=8 * CM,
    )
    layout = layout_with(title, body)
    band = title_band(layout, manifest)
    assert band.cy > 0, "щель над заголовком в этом шаблоне есть"

    placed = place(manifest, layout, blocks_of())

    callout = next(block for block in placed if block.block_id == "b02")
    assert callout.bbox is not None
    assert callout.bbox.intersection_area(band) == 0
    assert callout.bbox.y >= title.bbox.bottom


def test_a_free_block_may_stand_beside_a_half_width_title(
    manifest: TemplateManifest,
) -> None:
    """Норма: правка занимает полосу **над** заголовком, а не место рядом с ним.

    Так устроен макет «Слайд со спикером» Education (L14): заголовок слева, схема справа
    на всю высоту слайда — и это правильная композиция, ломать её правка не должна.
    """
    title = PlaceholderSpec(
        idx=0, ph_type="TITLE", role=TextRole.TITLE,
        x=2 * CM, y=2 * CM, cx=14 * CM, cy=2 * CM,
    )
    body = PlaceholderSpec(
        idx=1, ph_type="BODY", role=TextRole.BODY,
        x=2 * CM, y=5 * CM, cx=14 * CM, cy=12 * CM,
    )
    layout = layout_with(title, body)
    blocks = [
        TextBlock(block_id="b01", role=TextRole.TITLE, text="Вывод слайда", placeholder_idx=0),
        BulletsBlock(
            block_id="b03", placeholder_idx=1,
            items=[BulletItem(text="Первый"), BulletItem(text="Второй")],
        ),
        CalloutBlock(
            block_id="b02", text="Ручная адаптация шаблонов съедает день",
            tone=CalloutTone.RISK,
        ),
    ]

    placed = place(manifest, layout, blocks)

    callout = next(block for block in placed if block.block_id == "b02")
    assert callout.bbox is not None
    assert callout.bbox.x >= title.bbox.right, "встал рядом, а не над заголовком"
    assert callout.bbox.y < title.bbox.bottom, "колонка рядом с заголовком осталась целой"


def test_a_slide_without_a_title_placeholder_is_laid_out_as_before(
    manifest: TemplateManifest,
) -> None:
    """Норма: заголовка в плейсхолдере нет — раскладка прежняя."""
    body = PlaceholderSpec(
        idx=1, ph_type="BODY", role=TextRole.BODY,
        x=2 * CM, y=8 * CM, cx=29 * CM, cy=6 * CM,
    )
    layout = layout_with(body)
    blocks = [
        BulletsBlock(
            block_id="b01", placeholder_idx=1,
            items=[BulletItem(text="Первый"), BulletItem(text="Второй")],
        ),
        CalloutBlock(
            block_id="b02", text="Ручная адаптация шаблонов съедает день",
            tone=CalloutTone.RISK,
        ),
    ]

    placed = place(manifest, layout, blocks)

    callout = next(block for block in placed if block.block_id == "b02")
    assert callout.bbox is not None
    assert callout.bbox.y == manifest.content_bbox.y, "верх области контента свободен"


def test_a_title_at_the_top_of_the_content_area_is_unchanged(
    manifest: TemplateManifest,
) -> None:
    """Норма: рамка заголовка и так начинается от верха области — расширять нечего."""
    content = manifest.content_bbox
    title = PlaceholderSpec(
        idx=0, ph_type="TITLE", role=TextRole.TITLE,
        x=content.x, y=content.y, cx=content.cx, cy=2 * CM,
    )
    layout = layout_with(title)

    placed = place(manifest, layout, blocks_of())

    callout = next(block for block in placed if block.block_id == "b02")
    assert callout.bbox is not None
    assert callout.bbox.y >= title.bbox.bottom


@pytest.mark.parametrize("name", ["education", "vk-tech", "workspace"])
def test_no_free_block_lands_above_a_title_on_the_runs(name: str) -> None:
    """Мерило change на прогоне 29.09: пересечений с полосой заголовка нет.

    «До»: Education s02 (выноска) и s08 (схема) занимали по 45 % этой полосы.
    """
    run = from_fixture(FIXTURES / name)
    layouts = {layout.layout_id: layout for layout in run.manifest.layouts}
    rules = DesignRules(run.manifest, run.design_system)
    made = composer()

    for slide in run.deck.slides:
        layout = layouts.get(slide.layout_id)
        if slide.recipe_id or layout is None:
            continue
        heading = next(
            (
                layout.placeholder(block.placeholder_idx)
                for block in slide.blocks
                if isinstance(block, TextBlock)
                and block.role is TextRole.TITLE
                and block.placeholder_idx is not None
            ),
            None,
        )
        freed = [
            block.block_id
            for block in slide.blocks
            if getattr(block, "placeholder_idx", None) is None
        ]
        if heading is None or not freed:
            continue
        stripped = [
            block.model_copy(update={"x": None, "y": None, "cx": None, "cy": None})
            if block.block_id in freed
            else block
            for block in slide.blocks
        ]
        content = run.manifest.content_bbox
        band = BBox(
            x=heading.bbox.x, y=content.y, cx=heading.bbox.cx,
            cy=heading.bbox.bottom - content.y,
        )
        placed = made._place_free(
            stripped, freed, layout, run.manifest, slide.slide_id, rules
        )
        for block in placed:
            if block.block_id in freed and block.bbox is not None:
                assert block.bbox.intersection_area(band) == 0, (
                    f"{name} {slide.slide_id}: {block.block_id} встал над заголовком"
                )
