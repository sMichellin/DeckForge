"""Разрешение геометрии блока для проверок вёрстки. Change (15).

Координаты в `SlideIR` необязательны: если блок лёг в плейсхолдер, рамку задаёт макет
шаблона, а не IR (ADR-002). Каждая проверка вёрстки начинается с одного и того же
вопроса «где этот блок на самом деле», поэтому ответ живёт здесь, а не повторяется семь раз.

Блок без собственных координат и без плейсхолдера рамки не имеет. Это не ошибка вёрстки,
а отсутствие сведений: такой блок проверки геометрии пропускают, а не считают лежащим в нуле.
"""

from __future__ import annotations

from deckforge.domain.base import BBox
from deckforge.domain.slide import (
    Block,
    BulletsBlock,
    ImageBlock,
    KpiBlock,
    SlideIR,
    TableBlock,
    TextBlock,
)
from deckforge.domain.template import LayoutSpec, PlaceholderSpec, TemplateManifest

#: Блоки, которые несут текст: для них осмысленны переполнение, обрезка и контраст.
TEXT_BLOCKS = (TextBlock, BulletsBlock, TableBlock, KpiBlock)

#: Доля стороны слайда, начиная с которой блок или фигура — подложка, а не контент.
#: Величина безразмерная и от шаблона не зависит: это про приём, а не про бренд.
FULL_BLEED_SHARE = 0.95


def layout_of(slide: SlideIR, manifest: TemplateManifest) -> LayoutSpec | None:
    return manifest.layout(slide.layout_id)


def block_bbox(block: Block, layout: LayoutSpec | None) -> BBox | None:
    """Рамка блока: своя из IR, иначе — плейсхолдера макета. Нет ни той, ни другой — `None`."""
    own = block.bbox
    if own is not None:
        return own
    idx = getattr(block, "placeholder_idx", None)
    if idx is None or layout is None:
        return None
    placeholder = layout.placeholder(idx)
    return placeholder.bbox if placeholder is not None else None


def placeholder_of(block: Block, layout: LayoutSpec | None) -> PlaceholderSpec | None:
    """Плейсхолдер, в который лёг блок.

    Нужен проверкам шрифта и кегля: гарнитура и размер — свойства **этого** плейсхолдера,
    а не роли целиком. На шаблонах кейса тема заявляет одну гарнитуру, а плейсхолдеры
    набраны другой, и сверка с темой дала бы находку на каждом слайде.
    """
    if layout is None:
        return None
    idx = getattr(block, "placeholder_idx", None)
    return layout.placeholder(idx) if idx is not None else None


def positioned_blocks(
    slide: SlideIR, manifest: TemplateManifest
) -> list[tuple[Block, BBox]]:
    """Блоки слайда, у которых рамку удалось определить."""
    layout = layout_of(slide, manifest)
    out: list[tuple[Block, BBox]] = []
    for block in slide.blocks:
        bbox = block_bbox(block, layout)
        if bbox is not None:
            out.append((block, bbox))
    return out


def block_text(block: Block) -> str:
    """Весь текст блока одной строкой — для плотности, заглушек и орфографии."""
    if isinstance(block, TextBlock):
        return block.text
    if isinstance(block, BulletsBlock):
        return " ".join(item.text for item in block.items)
    if isinstance(block, TableBlock):
        cells = list(block.header) + [cell for row in block.rows for cell in row]
        return " ".join(cells)
    if isinstance(block, KpiBlock):
        return " ".join(f"{item.value} {item.label}" for item in block.items)
    if isinstance(block, ImageBlock):
        return block.alt_text or ""
    return ""


def slide_text(slide: SlideIR) -> str:
    return " ".join(part for part in (block_text(b) for b in slide.blocks) if part)


def carries_text(block: Block) -> bool:
    return isinstance(block, TEXT_BLOCKS)


def covers(bbox: BBox, slide: BBox, share: float) -> bool:
    """Блок занимает не меньше доли `share` по обеим сторонам слайда — сделан «в край».

    Полноэкранная подложка — приём шаблона, а не нарушение полей, поэтому проверки
    полей и заполненности обязаны её отличать.
    """
    return bbox.cx >= slide.cx * share and bbox.cy >= slide.cy * share
