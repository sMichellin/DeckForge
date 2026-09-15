"""Слой `layout`: вписывание текста, constraints, детект переполнения до записи.

Change (12) `layout-fitting`. LLM здесь не вызывается (ARCHITECTURE.md §3).
"""

from deckforge.layout.fitting import fit_text
from deckforge.layout.metrics import measure_text

__all__ = ["fit_text", "measure_text"]
