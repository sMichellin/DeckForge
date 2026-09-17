"""Слой `pipeline`: LangGraph-граф, состояние, HITL, чекпойнты (ADR-006). Change (17).

Узлы — тонкие обёртки над сервисами слоёв. Бизнес-логика в графе не живёт.

Транспорт (CLI, API потока C) зовёт `generate_variant` и про LangGraph не знает.
"""

from deckforge.pipeline.budget import BudgetTracker
from deckforge.pipeline.deps import Deps, PipelineError
from deckforge.pipeline.graph import build_graph
from deckforge.pipeline.run import (
    RunResult,
    build_deps,
    collect_content_paths,
    generate_variant,
    load_brief,
    variants_for,
)
from deckforge.pipeline.state import DeckState

__all__ = [
    "BudgetTracker",
    "DeckState",
    "Deps",
    "PipelineError",
    "RunResult",
    "build_deps",
    "build_graph",
    "collect_content_paths",
    "generate_variant",
    "load_brief",
    "variants_for",
]
