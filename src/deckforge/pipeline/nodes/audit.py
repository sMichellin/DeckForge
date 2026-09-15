"""Узел `audit`. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

from deckforge.pipeline.state import DeckState


async def audit_node(state: DeckState) -> DeckState:
    raise NotImplementedError("change (17) pipeline-orchestration")
