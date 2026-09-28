"""Граф генерации. Change (17) `pipeline-orchestration`.

    parse_template ─┐        ┌─ by_example → assign ─┐
                    ├→ plan ─┤                       ├→ compose → fit → render → audit → hitl ─┐
    ingest_content ─┘        └─ legacy ──────────────┘             ↑                             │
                                                                   └──────── fix ←── (выбрано) ──┤
                                                                               export ←─ accept ─┘

Узел `assign` (ADR-009) стоит только на пути `by_example`: пример выбирается до текста.
Путь `legacy` его обходит и собирается как до плана Б.

Парсинг шаблона и ingestion контента идут параллельно: они ни в чём друг от друга
не зависят, а по бюджету §12 стоят 25 и 15 с.

Виток починки ведёт в `fit`, а не в `compose` — обоснование в `nodes/fix.py`.

Чекпойнты — sqlite: долгая задача переживает перезапуск, HITL прерывает граф на узле
`hitl` и возобновляет его после выбора пользователя.
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes.assign import assign_node
from deckforge.pipeline.nodes.audit import audit_node
from deckforge.pipeline.nodes.compose import compose_node
from deckforge.pipeline.nodes.export import export_node
from deckforge.pipeline.nodes.fit import fit_node
from deckforge.pipeline.nodes.fix import fix_node
from deckforge.pipeline.nodes.hitl import hitl_node
from deckforge.pipeline.nodes.ingest import ingest_node
from deckforge.pipeline.nodes.parse import parse_node
from deckforge.pipeline.nodes.plan import plan_node
from deckforge.pipeline.nodes.render import render_node
from deckforge.pipeline.state import DeckState


def route_after_plan(state: DeckState) -> Literal["assign", "compose"]:
    """Путь сборки (ADR-009): `by_example` идёт через `assign`, `legacy` — сразу в `compose`.

    Чекпойнт до плана Б пути не несёт — он собран путём `legacy`.
    """
    return "assign" if state.get("composition_path") == "by_example" else "compose"


def route_after_hitl(state: DeckState) -> Literal["fix", "export"]:
    """Что выбрали чинить — то и чиним; ничего не выбрали — колода готова."""
    return "fix" if state.get("selected_fixes") else "export"


def route_after_fix(state: DeckState) -> Literal["fit", "export"]:
    """Фикс применён — колода пересобирается и перепроверяется.

    Не применён (change 19 ещё не приехал) — виток не повторяется: крутить граф,
    который заведомо ничего не меняет, значит жечь бюджет §12 впустую.
    """
    return "fit" if state.get("fix_applied") else "export"


def build_graph(checkpointer: Any | None = None) -> Any:
    """Собирает и компилирует граф.

    `checkpointer` — реализация LangGraph (`AsyncSqliteSaver` для долгой задачи,
    `InMemorySaver` для теста). Без него HITL-прерывание невозможно: возобновлять
    будет нечего.
    """
    graph: StateGraph[DeckState, Deps, DeckState, DeckState] = StateGraph(
        DeckState, context_schema=Deps
    )

    graph.add_node("parse_template", parse_node)
    graph.add_node("ingest_content", ingest_node)
    graph.add_node("plan", plan_node)
    graph.add_node("assign", assign_node)
    graph.add_node("compose", compose_node)
    graph.add_node("fit", fit_node)
    graph.add_node("render", render_node)
    graph.add_node("audit", audit_node)
    graph.add_node("hitl", hitl_node)
    graph.add_node("fix", fix_node)
    graph.add_node("export", export_node)

    graph.add_edge(START, "parse_template")
    graph.add_edge(START, "ingest_content")
    # Планирование ждёт обоих: ему нужны и виды макетов, и факты.
    graph.add_edge("parse_template", "plan")
    graph.add_edge("ingest_content", "plan")

    graph.add_conditional_edges("plan", route_after_plan, ["assign", "compose"])
    graph.add_edge("assign", "compose")
    graph.add_edge("compose", "fit")
    graph.add_edge("fit", "render")
    graph.add_edge("render", "audit")
    graph.add_edge("audit", "hitl")
    graph.add_conditional_edges("hitl", route_after_hitl, ["fix", "export"])
    graph.add_conditional_edges("fix", route_after_fix, ["fit", "export"])
    graph.add_edge("export", END)

    return graph.compile(checkpointer=checkpointer)
