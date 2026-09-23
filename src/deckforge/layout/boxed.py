"""Цитата и callout: раскладка внутри рамки блока. Change `draw-by-the-design-system`.

Одна раскладка на три потребителя — вписывание, запись pptx и html, — как у составных
компонентов (`layout.diagram`): расходиться им нельзя, pptx и html показывают одно и то же.

Оба блока устроены одинаково, как на странице дизайн-системы (#142): акцентная полоса
слева и текст справа от неё через отбивку. У цитаты под текстом — строка автора
мелким кеглем, у callout над текстом — подпись вида («Ключевой инсайт», «Риск»)
полужирным. Полоса, отбивка и кегли — из дизайн-системы (`DesignRules`), своих чисел нет.
"""

from __future__ import annotations

from dataclasses import dataclass

from deckforge.domain.base import BBox
from deckforge.domain.slide import CalloutBlock, QuoteBlock
from deckforge.domain.units import TEXT_FRAME_INSET_Y_EMU
from deckforge.layout.by_design import BoxedStyle, DesignRules

#: Знак перед именем автора цитаты — типографика, а не оформление шаблона.
AUTHOR_DASH = "— "

BoxedBlock = QuoteBlock | CalloutBlock


@dataclass(frozen=True)
class Paragraph:
    """Абзац блока: текст, кегль, начертание и его роль внутри блока."""

    text: str
    size_pt: float
    bold: bool
    #: Подпись вида у callout: цвет у неё акцентный, а не цвет текста.
    label: bool = False
    #: Строка автора у цитаты: кегль подписи.
    minor: bool = False


@dataclass(frozen=True)
class BoxedGeometry:
    #: Полоса слева — по высоте набранного текста, по середине рамки.
    bar: BBox
    #: Рамка текста справа от полосы и отбивки, во всю высоту блока.
    frame: BBox


def style_of(block: BoxedBlock, rules: DesignRules) -> BoxedStyle:
    if isinstance(block, QuoteBlock):
        return rules.quote_style()
    return rules.callout_style(block.tone)


def text_frame(box: BBox, style: BoxedStyle) -> BBox:
    """Рамка текста: рамка блока без полосы и отбивки слева."""
    inset = style.inset(box.cx)
    shift = min(box.cx - 1, inset.bar_emu + inset.pad_emu)
    return BBox(x=box.x + shift, y=box.y, cx=max(1, box.cx - shift), cy=box.cy)


def paragraphs(
    block: BoxedBlock, style: BoxedStyle, size_pt: float, *, bold: bool = False
) -> list[Paragraph]:
    """Абзацы блока при кегле текста `size_pt`. `bold` — начертание роли в шкале."""
    if isinstance(block, QuoteBlock):
        out = [Paragraph(block.text, size_pt, bold)]
        if block.author:
            out.append(
                Paragraph(
                    AUTHOR_DASH + block.author, min(style.minor_pt, size_pt), False, minor=True
                )
            )
        return out
    out = [Paragraph(style.label, size_pt, True, label=True)] if style.label else []
    return [*out, Paragraph(block.text, size_pt, bold)]


def geometry(box: BBox, style: BoxedStyle, required_cy_emu: int | None) -> BoxedGeometry:
    """Полоса и рамка текста. Полоса — по высоте текста, а не рамки: решатель отдаёт
    свободному блоку всю свободную площадь, и полоса во всю её высоту при трёх строках
    посередине читалась бы разделителем колонок, а не знаком цитаты."""
    inset = style.inset(box.cx)
    ink = (required_cy_emu or box.cy) + 2 * TEXT_FRAME_INSET_Y_EMU
    height = max(1, min(box.cy, ink))
    bar = BBox(
        x=box.x,
        y=box.y + (box.cy - height) // 2,
        cx=max(1, min(inset.bar_emu, box.cx)),
        cy=height,
    )
    return BoxedGeometry(bar=bar, frame=text_frame(box, style))
