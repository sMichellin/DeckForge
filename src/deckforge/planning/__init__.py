"""Слой `planning`: бриф + контент + манифест → `DeckPlan`. Change (10) `deck-planning`.

Не знает про EMU, координаты и python-pptx (ARCHITECTURE.md §3).
"""

from deckforge.planning.planner import DeckPlanner

__all__ = ["DeckPlanner"]
