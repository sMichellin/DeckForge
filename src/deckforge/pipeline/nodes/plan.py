"""Узел `plan`. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

from langgraph.runtime import Runtime

from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState
from deckforge.planning.planner import DeckPlanner, slides_for


async def plan_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """`ContentPackage` + виды макетов → `DeckPlan` (change 10). Один вызов LLM."""
    deps = runtime.context
    client, degraded = deps.llm_for("plan")
    planner = DeckPlanner(client, profile=deps.prompt_profile)

    async with timed(deps, "plan") as timings:
        plan = await planner.plan(
            state["content"], state["manifest"], state["variant"], state["seed"]
        )

    # Нарратив проверен планировщиком, но чинить его молча нельзя (change 10):
    # замечания едут в отчёт прогона, а не растворяются внутри слоя.
    notes = [f"план: {note}" for note in plan.narrative_check.notes]

    # Материала может не хватить на запрошенное число слайдов. Урезать молча нельзя:
    # автор просил двенадцать и должен узнать, почему их восемь.
    brief = state["content"].brief
    fits = slides_for(state["content"], brief.purpose, brief.target_slides)
    if fits < brief.target_slides:
        notes.append(
            f"план: слайдов {len(plan.slides)} вместо запрошенных {brief.target_slides} — "
            f"на {len(state['content'].facts)} фактах больше вышло бы полупустыми"
        )
    return {
        "plan": plan,
        "stage_timings_s": timings,
        "notes": notes,
        "degradations": [degraded] if degraded else [],
    }
