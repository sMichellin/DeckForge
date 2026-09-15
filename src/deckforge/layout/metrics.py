"""Метрики текста через `fontTools`. Change (12) `layout-fitting`.

Считаем **до** записи файла — это единственная защита от переполнения на чужих шрифтах (§15).
"""

from __future__ import annotations

from deckforge.domain.base import BBox


class TextMetrics:
    width_emu: int
    height_emu: int
    lines: int


def measure_text(
    text: str, *, font_family: str, size_pt: float, box: BBox, line_spacing: float = 1.0
) -> TextMetrics:
    raise NotImplementedError("change (12) layout-fitting")
