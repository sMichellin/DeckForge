"""Constraint-решатель (kiwisolver) для блоков без плейсхолдера. Change (12)."""

from __future__ import annotations

from deckforge.domain.base import BBox
from deckforge.domain.template import TemplateManifest


def solve_positions(
    blocks: list[tuple[str, BBox | None]], manifest: TemplateManifest
) -> dict[str, BBox]:
    """Раскладывает блоки по сетке, не выходя за поля и не перекрываясь."""
    raise NotImplementedError("change (12) layout-fitting")
