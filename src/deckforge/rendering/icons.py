"""Иконки Lucide (ISC) / Tabler (MIT): SVG → перекраска в `color_ref` → вставка вектором.

Change (21) `smartart-icons`. Растр не используется (C3).
"""

from __future__ import annotations

from deckforge.domain.slide import IconBlock
from deckforge.domain.template import TemplateManifest


def add_icon(slide: object, block: IconBlock, manifest: TemplateManifest) -> object:
    raise NotImplementedError("change (21) smartart-icons")
