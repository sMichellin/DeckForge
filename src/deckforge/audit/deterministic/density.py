"""Проверки плотности (§5.1). Пороги — из `configs/audit_checks.yaml`, не из кода.

Плотность считается по `SlideIR`, а не по готовому файлу, и это принципиально.
В `.pptx` вложенности нет: плашка внутри плашки — такой же прямоугольник, как сама
плашка, а декор макета — тоже прямоугольник. Счёт «сколько на слайде блоков» по фигурам
файла врёт, причём в первую очередь на слайдах, собранных аккуратно. В плане структура
задана явно, и счёт честный.
"""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.findings import make_finding
from deckforge.audit.geometry import (
    FULL_BLEED_SHARE,
    block_bbox,
    covers,
    layout_of,
    positioned_blocks,
)
from deckforge.audit.registry import CheckContext, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import AutoFix, Severity
from deckforge.domain.slide import BulletsBlock, ChartBlock, TableBlock


@check(id="density.too_many_bullets", deterministic=True, severity=Severity.WARNING,
       auto_fix=AutoFix.SPLIT_SLIDE, title="Больше 6 буллетов на слайде")
def too_many_bullets(ctx: CheckContext) -> Iterable[Finding]:
    """Больше 6 буллетов на слайде."""
    limit = int(ctx.param("max_bullets", 6))
    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        bullets = [b for b in slide.blocks if isinstance(b, BulletsBlock)]
        total = sum(len(block.items) for block in bullets)
        if total <= limit or not bullets:
            continue
        first = bullets[0]
        yield make_finding(
            check_id="density.too_many_bullets",
            slide_id=slide.slide_id,
            block_id=first.block_id,
            bbox=block_bbox(first, layout),
            reason=f"count:{total}",
            message=f"На слайде {total} пунктов при допустимых {limit}",
            evidence={"count": str(total), "limit": str(limit)},
        )


@check(id="density.bullet_too_long", deterministic=True, severity=Severity.WARNING,
       auto_fix=AutoFix.SHORTEN_TEXT, title="Буллет длиннее 15 слов")
def bullet_too_long(ctx: CheckContext) -> Iterable[Finding]:
    """Буллет длиннее 15 слов."""
    limit = int(ctx.param("max_words", 15))
    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            if not isinstance(block, BulletsBlock):
                continue
            for position, item in enumerate(block.items):
                words = len(item.text.split())
                if words <= limit:
                    continue
                yield make_finding(
                    check_id="density.bullet_too_long",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=block_bbox(block, layout),
                    reason=f"item:{position}",
                    message=f"Пункт {position + 1}: {words} слов при допустимых {limit}",
                    evidence={"words": str(words), "item_index": str(position)},
                )


@check(id="density.table_too_big", deterministic=True, severity=Severity.WARNING,
       title="Таблица больше 7 строк или 5 колонок")
def table_too_big(ctx: CheckContext) -> Iterable[Finding]:
    """Таблица больше 7 строк или 5 колонок."""
    max_rows = int(ctx.param("max_rows", 7))
    max_cols = int(ctx.param("max_cols", 5))
    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            if not isinstance(block, TableBlock):
                continue
            rows = len(block.rows) + (1 if block.header else 0)
            cols = max([len(block.header)] + [len(row) for row in block.rows] or [0])
            if rows <= max_rows and cols <= max_cols:
                continue
            yield make_finding(
                check_id="density.table_too_big",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=block_bbox(block, layout),
                reason=f"size:{rows}x{cols}",
                message=(
                    f"Таблица {rows}×{cols} при допустимых {max_rows}×{max_cols}: "
                    "на слайде её будет не прочесть"
                ),
                evidence={"rows": str(rows), "cols": str(cols)},
            )


@check(id="density.too_many_series", deterministic=True, severity=Severity.WARNING,
       title="Больше 5 серий на диаграмме")
def too_many_series(ctx: CheckContext) -> Iterable[Finding]:
    """Больше 5 серий на диаграмме."""
    limit = int(ctx.param("max_series", 5))
    content = ctx.content
    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            if not isinstance(block, ChartBlock):
                continue
            dataset = content.dataset(block.dataset_ref) if content is not None else None
            count = len(dataset.series) if dataset is not None else len(block.series_color_refs)
            if count <= limit:
                continue
            yield make_finding(
                check_id="density.too_many_series",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=block_bbox(block, layout),
                reason=f"series:{count}",
                message=f"На диаграмме {count} серий при допустимых {limit}",
                evidence={"series": str(count), "dataset_ref": block.dataset_ref},
            )


@check(id="density.fill_ratio", deterministic=True, severity=Severity.WARNING,
       title="Слайд заполнен меньше четверти или больше трёх четвертей")
def fill_ratio(ctx: CheckContext) -> Iterable[Finding]:
    """Слайд заполнен меньше четверти или больше трёх четвертей."""
    min_ratio = ctx.param("min_ratio", 0.25)
    max_ratio = ctx.param("max_ratio", 0.75)
    slide_box = ctx.manifest.slide_size.bbox

    for slide in ctx.deck.slides:
        placed = positioned_blocks(slide, ctx.manifest)
        # Полноэкранная подложка заняла бы весь слайд и сделала бы проверку бессмысленной:
        # слайд с фотографией в край всегда «переполнен», хотя это приём шаблона.
        boxes = [bbox for _, bbox in placed if not covers(bbox, slide_box, FULL_BLEED_SHARE)]
        if not boxes:
            continue
        ratio = sum(bbox.area for bbox in boxes) / slide_box.area
        if min_ratio <= ratio <= max_ratio:
            continue
        verdict = "полупустой" if ratio < min_ratio else "перегруженный"
        yield make_finding(
            check_id="density.fill_ratio",
            slide_id=slide.slide_id,
            reason=f"fill:{verdict}",
            message=(
                f"Слайд {verdict}: занято {ratio:.0%} площади при допустимых "
                f"{min_ratio:.0%}–{max_ratio:.0%}"
            ),
            evidence={"ratio": f"{ratio:.3f}"},
        )
