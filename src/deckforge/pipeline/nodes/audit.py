"""Узел `audit`. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

import asyncio
from pathlib import Path

from langgraph.runtime import Runtime

from deckforge.audit.runner import AuditRunner
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState


def _read_previews(previews: dict[str, Path]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for slide_id, path in previews.items():
        if path.is_file():
            out[slide_id] = path.read_bytes()
    return out


async def audit_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """Детерминированные проверки и VLM-судья по готовой колоде (changes 15, 18)."""
    deps = runtime.context
    previews = state.get("previews") or {}

    degradations: list[str] = []
    vlm = deps.vlm if deps.run.audit.get("run_semantic", True) else None
    if vlm is not None and deps.budget.behind_schedule("audit"):
        # Рычаг §15: смысловой аудит — самая дорогая стадия, а 25 детерминированных
        # проверок остаются на месте и стоят миллисекунды.
        vlm = None
        degradations.append("audit: смысловой аудит выключен — остатка бюджета не хватает (§15)")

    runner = AuditRunner()
    async with timed(deps, "audit") as timings:
        report = await runner.run(
            state["deck"],
            state["manifest"],
            state["content"],
            previews=await asyncio.to_thread(_read_previews, previews),
            deck_path=state.get("pptx_path"),
            vlm=vlm,
        )

    return {
        "audit": report,
        "skipped_checks": runner.skipped_checks,
        "stage_timings_s": timings,
        "degradations": degradations,
    }
