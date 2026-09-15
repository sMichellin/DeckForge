"""Слой `composition`: `DeckPlan` + манифест → `SlideIR[]`. Change (11) `slide-composition`.

Не пишет в файл. Параллелится по слайдам, бюджет 100 с (§12).
"""

from deckforge.composition.composer import SlideComposer

__all__ = ["SlideComposer"]
