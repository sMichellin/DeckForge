"""Разбор `ppt/theme/theme1.xml`: clrScheme и fontScheme. Change (4) `theme-extraction`.

python-pptx не отдаёт тему целиком, поэтому здесь lxml напрямую.
"""

from __future__ import annotations

from deckforge.domain.template import Theme

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def parse_theme(theme_xml: bytes) -> Theme:
    """12 цветов схемы + мажорная/минорная гарнитура. Пустых ключей быть не должно."""
    raise NotImplementedError("change (4) theme-extraction")
