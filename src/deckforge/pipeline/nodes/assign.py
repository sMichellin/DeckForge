"""Узел `assign` (план Б, ADR-009). Change `the-assign-node`.

Пример выбирается до текста: между `plan` и `compose` назначения ложатся на всю колоду
сразу. Узел — тонкая обёртка (ADR-006): паспорта строит `composition.passport`, примеры
назначает `composition.assign`, здесь — только вызов, время стадии и то, что увидит отчёт.

Узел стоит только на пути `by_example` (`composition.path`): путь `legacy` его обходит
и собирается байт в байт как раньше. Паспорта строятся здесь, а не в узле `parse`, по той
же причине — `legacy` они не нужны, а 1–3 с на шаблон ему незачем платить.
"""

from __future__ import annotations

import asyncio

from langgraph.runtime import Runtime

from deckforge.composition.assign import assign_recipes
from deckforge.composition.passport import with_passports
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState


async def assign_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """Паспорта примеров и назначение примеров на всю колоду — до текста."""
    deps = runtime.context
    async with timed(deps, "assign") as timings:
        design, report = await asyncio.to_thread(
            with_passports, state["design_system"], state["manifest"], deps.fonts
        )
        assignments = assign_recipes(state["plan"], design, seed=state["seed"])

    without = sum(1 for a in assignments if a.recipe_id is None)
    return {
        # Та же дизайн-система, но с паспортами: по ним `compose` пишет текст под места,
        # а вёрстка удаляет группы. Остальные узлы видят ровно её (RG27).
        "design_system": design,
        "assignments": assignments,
        "notes": [
            f"паспорт у {len(report.with_passport)} примеров из {len(design.recipes)}",
            *report.notes(),
            f"примеры назначены до текста: с примером {len(assignments) - without}, "
            f"путём дизайн-системы {without}",
        ],
        "stage_timings_s": timings,
    }
