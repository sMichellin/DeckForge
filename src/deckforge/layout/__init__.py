"""Слой `layout`: вписывание текста, constraints, детект переполнения до записи.

Change (12) `layout-fitting`. LLM здесь не вызывается (ARCHITECTURE.md §3).
"""

from deckforge.layout.constraints import solve_positions
from deckforge.layout.fitting import LayoutFitError, fit_block, fit_slide, fit_text
from deckforge.layout.fonts import FontLibrary, FontNotFoundError
from deckforge.layout.metrics import TextMetrics, measure_text

__all__ = [
    "FontLibrary",
    "FontNotFoundError",
    "LayoutFitError",
    "TextMetrics",
    "fit_block",
    "fit_slide",
    "fit_text",
    "measure_text",
    "solve_positions",
]
