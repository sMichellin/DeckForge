"""Сетка и направляющие. Change (4) `theme-extraction`.

Если направляющих нет в XML мастера, они выводятся кластеризацией координат плейсхолдеров.
"""

from __future__ import annotations

from deckforge.domain.template import Grid, LayoutSpec, SlideSize


def extract_guides(master_xml: bytes) -> tuple[list[int], list[int]] | None:
    raise NotImplementedError("change (4) theme-extraction")


def infer_grid(layouts: list[LayoutSpec], slide_size: SlideSize) -> Grid:
    raise NotImplementedError("change (4) theme-extraction")
