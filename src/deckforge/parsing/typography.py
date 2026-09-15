"""Вывод типографической шкалы шаблона из master/layout. Change (4) `theme-extraction`."""

from __future__ import annotations

from deckforge.domain.template import TypographyStep


def derive_scale(master_xml: bytes, layout_xmls: list[bytes]) -> list[TypographyStep]:
    """Собрать ступени title/subtitle/body/caption из lvl1pPr..lvl9pPr и defRPr."""
    raise NotImplementedError("change (4) theme-extraction")
