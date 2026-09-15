"""Детерминированные правила нарратива: одна мысль на слайд, связность соседей."""

from __future__ import annotations

from deckforge.domain.plan import DeckPlan, NarrativeCheck


def check_narrative(plan: DeckPlan) -> NarrativeCheck:
    raise NotImplementedError("change (10) deck-planning")
