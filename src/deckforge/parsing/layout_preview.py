"""Превью макета для VLM-классификации. Change (5) `layout-classification`.

Классификатору нужен не красивый слайд, а **структура**: что за блоки, какого размера,
как расставлены. Схема из прямоугольников даёт ровно это и обходится без LibreOffice,
поэтому классификация не ждёт change (6) и не тратит бюджет на конвертацию 30–40 макетов.

Полноценный рендер (`audit/preview.py`, change (6)) нужен там, где важен реальный вид
слайда: контекстуальный аудит по готовой колоде. Оба поставщика реализуют один протокол,
и классификатор не знает, какой ему дали.
"""

from __future__ import annotations

import io
from typing import Protocol

from PIL import Image, ImageDraw

from deckforge.domain.enums import TextRole
from deckforge.domain.template import LayoutSpec, ShapeKind

#: Ширина схемы в пикселях. Больше не нужно: VLM различает блоки и на такой.
PREVIEW_WIDTH_PX = 768

#: Цвета схемы намеренно свои, а не из шаблона: классификатор рассуждает о структуре,
#: и палитра шаблона здесь только мешала бы — тёмный текст на тёмном фоне не читается.
_BG = (250, 250, 252)
_EDGE = (30, 30, 40)
_FILL_BY_ROLE = {
    TextRole.TITLE: (210, 224, 255),
    TextRole.SUBTITLE: (226, 236, 255),
    TextRole.BODY: (238, 241, 246),
    TextRole.CAPTION: (245, 245, 247),
}
_FILL_OTHER = (232, 245, 238)

#: Фигуры вне плейсхолдеров рисуются иначе: в них ничего не положишь, но они определяют,
#: как макет выглядит. Картинка отдельно — это самый сильный сигнал о виде макета.
_FILL_BY_SHAPE = {
    ShapeKind.PICTURE: (198, 214, 232),
    ShapeKind.CHART: (214, 232, 214),
    ShapeKind.TABLE: (222, 226, 232),
    ShapeKind.TEXT: (240, 236, 226),
    ShapeKind.SHAPE: (236, 236, 240),
}
_EDGE_SHAPE = (120, 124, 136)


class Boxed(Protocol):
    """Всё, у чего есть прямоугольник: плейсхолдер и фигура рисуются одинаково."""

    @property
    def x(self) -> int: ...
    @property
    def y(self) -> int: ...
    @property
    def cx(self) -> int: ...
    @property
    def cy(self) -> int: ...


class LayoutPreviewProvider(Protocol):
    """Источник изображения макета для классификатора."""

    def render(self, layout: LayoutSpec, slide_cx: int, slide_cy: int) -> bytes: ...


class SchematicPreview:
    """Схема макета: прямоугольники плейсхолдеров с подписью типа и доли площади."""

    def __init__(self, width_px: int = PREVIEW_WIDTH_PX) -> None:
        self.width_px = width_px

    def render(self, layout: LayoutSpec, slide_cx: int, slide_cy: int) -> bytes:
        if slide_cx <= 0 or slide_cy <= 0:
            raise ValueError("размер слайда должен быть положительным")

        scale = self.width_px / slide_cx
        height_px = max(1, round(slide_cy * scale))
        canvas = Image.new("RGB", (self.width_px, height_px), _BG)
        draw = ImageDraw.Draw(canvas)

        # Рамка слайда: без неё VLM не видит, где кончается холст.
        draw.rectangle([0, 0, self.width_px - 1, height_px - 1], outline=_EDGE, width=2)

        # Фигуры вне плейсхолдеров идут первым слоем: в шаблонах это фон и фотографии,
        # поверх которых потом лежит контент. Пунктир отличает их от мест под наполнение.
        for shape in sorted(layout.shapes, key=lambda s: s.cx * s.cy, reverse=True):
            box = _scaled(shape, scale)
            draw.rectangle(
                box, fill=_FILL_BY_SHAPE.get(shape.kind, _FILL_OTHER), outline=_EDGE_SHAPE, width=1
            )
            if box[3] - box[1] >= 16 and box[2] - box[0] >= 50:
                draw.text((box[0] + 6, box[1] + 4), shape.kind.value, fill=_EDGE_SHAPE)

        # Крупные блоки рисуются первыми, чтобы мелкие не оказались под ними.
        for ph in sorted(layout.placeholders, key=lambda p: p.cx * p.cy, reverse=True):
            box = _scaled(ph, scale)
            fill = _FILL_BY_ROLE.get(ph.role, _FILL_OTHER) if ph.role else _FILL_OTHER
            draw.rectangle(box, fill=fill, outline=_EDGE, width=2)

            label = ph.role.value if ph.role else ph.ph_type.lower()
            if box[3] - box[1] >= 16 and box[2] - box[0] >= 40:
                draw.text((box[0] + 6, box[1] + 4), f"{label} #{ph.idx}", fill=_EDGE)

        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        return buffer.getvalue()


def _scaled(item: Boxed, scale: float) -> list[int]:
    return [
        round(item.x * scale),
        round(item.y * scale),
        round((item.x + item.cx) * scale),
        round((item.y + item.cy) * scale),
    ]


def describe_layout(layout: LayoutSpec, slide_cx: int, slide_cy: int) -> str:
    """Текстовое описание макета — то же самое словами.

    Идёт в промпт рядом с картинкой: у VLM ≤ 8B узнавание мелких подписей на схеме
    ненадёжно, а доли площади и координаты она разбирает из текста без ошибок.
    """
    area = slide_cx * slide_cy

    def geometry(item: Boxed) -> str:
        return (
            f"слева {item.x / slide_cx:.0%}, сверху {item.y / slide_cy:.0%}, "
            f"ширина {item.cx / slide_cx:.0%}, высота {item.cy / slide_cy:.0%}, "
            f"площадь {item.cx * item.cy / area:.0%} слайда"
        )

    lines = [f"Слайд {slide_cx}×{slide_cy} EMU."]
    lines.append(f"Места под контент ({len(layout.placeholders)}):")
    for ph in sorted(layout.placeholders, key=lambda p: (p.y, p.x)):
        role = f" (роль {ph.role.value})" if ph.role else ""
        lines.append(f"- {ph.ph_type.lower()} #{ph.idx}{role}: {geometry(ph)}")

    if layout.shapes:
        lines.append(
            f"Готовое оформление макета, менять его нельзя ({len(layout.shapes)}):"
        )
        for shape in sorted(layout.shapes, key=lambda s: (s.y, s.x)):
            text = f", текст «{shape.text}»" if shape.text else ""
            lines.append(f"- {shape.kind.value}: {geometry(shape)}{text}")
    return "\n".join(lines)
