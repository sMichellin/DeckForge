"""Узел `ingest`. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

import asyncio
from functools import partial

from langgraph.runtime import Runtime

from deckforge.parsing.content import ContentIngestor
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState


async def ingest_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """Контент-пакет → `ContentPackage` (change 7). Идёт параллельно с парсингом."""
    deps = runtime.context
    ingestor = ContentIngestor(asset_dir=deps.asset_dir)
    async with timed(deps, "ingest_content") as timings:
        content = await asyncio.to_thread(
            partial(ingestor.ingest, list(state["content_paths"]), deps.brief)
        )

    notes: list[str] = []
    if not content.facts and not content.datasets:
        notes.append("из контент-пакета не извлечено ни фактов, ни датасетов")
    return {"content": content, "stage_timings_s": timings, "notes": notes}
