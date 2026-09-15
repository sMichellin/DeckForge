"""Логотип, колонтитул, статичные фигуры мастера. Change (3) `template-parsing-core`."""

from __future__ import annotations

from deckforge.domain.template import Decor


def extract_decor(master_xml: bytes, media: dict[str, bytes]) -> Decor:
    raise NotImplementedError("change (3) template-parsing-core")
