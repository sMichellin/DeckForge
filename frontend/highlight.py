"""Подсветка находки на превью слайда. Change (23) `web-ui`.

Требование ТЗ — «находки с подсветкой прямо на слайде», и это не украшение: оно
показывает, что аудит встроен в пайплайн, а не приложен к нему отчётом. Пользователь
должен видеть **место**, а не читать координаты.

Рамка приходит долями слайда (`bbox_rel`), а не в EMU: размер слайда знает манифест,
который до интерфейса не доезжает, а доли работают при любом масштабе картинки.
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw

#: Цвета по тяжести находки. Не из палитры шаблона: это интерфейс инструмента,
#: а не слайд, и подсвечивать нарушение цветом самого шаблона — плохая идея,
#: рамка сольётся ровно там, где она нужнее всего.
SEVERITY_COLORS: dict[str, tuple[int, int, int]] = {
    "error": (224, 49, 49),
    "warning": (245, 159, 0),
    "info": (46, 107, 230),
}
FALLBACK_COLOR = (120, 120, 120)

#: Толщина рамки в долях меньшей стороны картинки: на превью 1500 px это ~4 px,
#: на уменьшенном — меньше. Фиксированная толщина на маленькой картинке съедает слайд.
OUTLINE_SHARE = 0.003
MIN_OUTLINE_PX = 2


def color_for(severity: str) -> tuple[int, int, int]:
    return SEVERITY_COLORS.get(severity.lower(), FALLBACK_COLOR)


def box_in_pixels(
    rel: dict[str, float], width: int, height: int
) -> tuple[int, int, int, int]:
    """Доли слайда → прямоугольник в пикселях картинки.

    Рамка подрезается по картинке: находка может выходить за край слайда — ровно это
    и ловит `layout.out_of_bounds`, — а рисовать за пределами холста нечем.
    """
    left = _clamp(rel.get("x", 0.0) * width, 0, width)
    top = _clamp(rel.get("y", 0.0) * height, 0, height)
    right = _clamp((rel.get("x", 0.0) + rel.get("cx", 0.0)) * width, 0, width)
    bottom = _clamp((rel.get("y", 0.0) + rel.get("cy", 0.0)) * height, 0, height)
    return (int(left), int(top), max(int(right), int(left) + 1), max(int(bottom), int(top) + 1))


def draw_findings(png: bytes, findings: list[dict[str, Any]]) -> bytes:
    """Превью с рамками вокруг находок, у которых рамка есть.

    Находка без `bbox_rel` — смысловая: она про слайд целиком, и обводить на нём
    нечего. Рисовать вокруг всего слайда значило бы утверждать, что виноват весь слайд.
    """
    image = Image.open(io.BytesIO(png)).convert("RGB")
    canvas = ImageDraw.Draw(image)
    outline = max(MIN_OUTLINE_PX, int(min(image.size) * OUTLINE_SHARE))

    for finding in findings:
        rel = finding.get("bbox_rel")
        if not isinstance(rel, dict):
            continue
        canvas.rectangle(
            box_in_pixels(rel, image.width, image.height),
            outline=color_for(str(finding.get("severity", ""))),
            width=outline,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def by_slide(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Находки по слайдам, в порядке появления. Без `slide_id` — в ключ `""`."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        grouped.setdefault(str(finding.get("slide_id") or ""), []).append(finding)
    return grouped


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
