"""Узел `parse`. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

import asyncio
from functools import partial

from langgraph.runtime import Runtime

from deckforge.parsing.layout_kind import LayoutClassifier
from deckforge.parsing.template import TemplateParser
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState


async def parse_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """Шаблон → `TemplateManifest` (changes 3–6). Идёт параллельно с ingestion."""
    deps = runtime.context
    classifier = LayoutClassifier(
        vlm=deps.layout_vlm,
        language=deps.brief.language,
        profile=deps.prompt_profile,
        base_seed=state["seed"],
    )
    parser = TemplateParser(cache_dir=deps.cache_dir, classifier=classifier)
    async with timed(deps, "parse_template") as timings:
        # Парсер синхронный и упирается в диск: поток освобождает цикл событий
        # для ingestion, который идёт в это же время.
        manifest = await asyncio.to_thread(partial(parser.parse, state["template_path"]))

    notes: list[str] = []
    if deps.layout_vlm is None:
        notes.append("классификация макетов: без VLM, только эвристика (change 5)")
    return {"manifest": manifest, "stage_timings_s": timings, "notes": notes}
