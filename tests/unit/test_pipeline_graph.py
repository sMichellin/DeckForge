"""Граф генерации: маршруты, редьюсеры и узлы без живых сервисов. Change (17).

Проверяется не качество колоды — его меряют слои, — а то, что граф ведёт колоду туда,
куда надо, и что ни один пропуск не выдаётся за успех.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langgraph.runtime import Runtime

from deckforge.config import RunConfig
from deckforge.domain.audit import AuditReport, Finding
from deckforge.domain.content import Brief
from deckforge.domain.enums import AutoFix, Severity, SlideIntent, TextRole
from deckforge.domain.plan import DeckPlan, SlidePlan
from deckforge.domain.slide import DeckIR, SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline.budget import STAGE_BUDGET_S, BudgetTracker
from deckforge.pipeline.deps import Deps, PipelineError
from deckforge.pipeline.graph import build_graph, route_after_fix, route_after_hitl
from deckforge.pipeline.nodes.fit import _ordered
from deckforge.pipeline.nodes.fix import fix_node
from deckforge.pipeline.nodes.hitl import hitl_node
from deckforge.pipeline.state import DeckState, _append, _merge_slides, _merge_timings


def brief() -> Brief:
    return Brief(purpose="product", audience="правление", target_slides=6, language="ru")


def deps(tmp_path: Path, **kwargs: Any) -> Deps:
    run = RunConfig(**kwargs.pop("run", {}))
    return Deps(brief=brief(), run=run, out_dir=tmp_path, **kwargs)


def runtime(deps_: Deps) -> Runtime[Deps]:
    return Runtime(context=deps_)


def slide_ir(slide_id: str) -> SlideIR:
    return SlideIR(
        slide_id=slide_id,
        layout_id="L07",
        variant="A",
        blocks=[TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text=slide_id)],
    )


def plan_of(*slide_ids: str) -> DeckPlan:
    return DeckPlan(
        deck_id="d1",
        variant="A",
        seed=1,
        slides=[
            SlidePlan(slide_id=sid, intent=SlideIntent.PROBLEM, headline=f"Вывод {sid}")
            for sid in slide_ids
        ],
    )


def finding(
    finding_id: str, fix: AutoFix = AutoFix.SHRINK_FONT, block_id: str | None = None
) -> Finding:
    return Finding(
        finding_id=finding_id,
        check_id="layout.text_overflow",
        deterministic=True,
        severity=Severity.ERROR,
        slide_id="s01",
        block_id=block_id,
        message="переполнение",
        auto_fix=fix,
    )


def deck_of(manifest: TemplateManifest, *slide_ids: str) -> DeckIR:
    return DeckIR(
        deck_id="d1",
        variant="A",
        template_id=manifest.template_id,
        seed=1,
        slides=[slide_ir(sid) for sid in slide_ids],
    )


# --- редьюсеры состояния -----------------------------------------------------


def test_recomposed_slide_replaces_the_previous_one() -> None:
    """Виток фиксов не должен удваивать слайды: слайд узнаётся по `slide_id`."""
    merged = _merge_slides([slide_ir("s01"), slide_ir("s02")], [slide_ir("s02")])
    assert [s.slide_id for s in merged] == ["s01", "s02"]


def test_messages_accumulate_instead_of_overwriting() -> None:
    assert _append(["а"], ["б"]) == ["а", "б"]


def test_parallel_stages_both_keep_their_timing() -> None:
    """`parse_template` и `ingest_content` пишут тайминги одновременно."""
    assert _merge_timings({"parse_template": 1.0}, {"ingest_content": 2.0}) == {
        "parse_template": 1.0,
        "ingest_content": 2.0,
    }


# --- порядок слайдов ---------------------------------------------------------


def test_deck_order_comes_from_the_plan_not_from_sorted_ids() -> None:
    """«s9» против «s10»: сортировка строк поставила бы девятый слайд после десятого."""
    state: DeckState = {
        "plan": plan_of("s09", "s10", "s11"),
        "slides": [slide_ir("s11"), slide_ir("s09"), slide_ir("s10")],
    }
    assert [s.slide_id for s in _ordered(state)] == ["s09", "s10", "s11"]


def test_slide_that_failed_to_compose_is_dropped_not_guessed() -> None:
    state: DeckState = {"plan": plan_of("s01", "s02"), "slides": [slide_ir("s02")]}
    assert [s.slide_id for s in _ordered(state)] == ["s02"]


# --- маршруты ----------------------------------------------------------------


def test_nothing_selected_means_the_deck_is_ready() -> None:
    assert route_after_hitl({}) == "export"
    assert route_after_hitl({"selected_fixes": [finding("f1")]}) == "fix"


def test_fix_that_changed_nothing_does_not_start_another_round() -> None:
    """Иначе граф крутил бы витки, заведомо ничего не меняющие, и жёг бюджет §12."""
    assert route_after_fix({"fix_applied": False}) == "export"
    assert route_after_fix({"fix_applied": True}) == "fit"


# --- узел hitl ---------------------------------------------------------------


async def test_batch_run_selects_only_findings_with_a_declared_fix(tmp_path: Path) -> None:
    report = AuditReport(
        deck_id="d1",
        variant="A",
        findings=[finding("f1"), finding("f2", AutoFix.NONE)],
    )
    out = await hitl_node({"audit": report, "fix_round": 0}, runtime(deps(tmp_path)))
    assert [f.finding_id for f in out["selected_fixes"]] == ["f1"]


async def test_auto_fix_turned_off_fixes_nothing(tmp_path: Path) -> None:
    report = AuditReport(deck_id="d1", variant="A", findings=[finding("f1")])
    context = deps(tmp_path, run={"audit": {"auto_fix": False}})
    out = await hitl_node({"audit": report, "fix_round": 0}, runtime(context))
    assert out["selected_fixes"] == []


async def test_fix_rounds_are_capped_and_the_cap_is_reported(tmp_path: Path) -> None:
    report = AuditReport(deck_id="d1", variant="A", findings=[finding("f1")])
    context = deps(tmp_path, run={"audit": {"max_fix_rounds": 1}})
    out = await hitl_node({"audit": report, "fix_round": 1}, runtime(context))
    assert out["selected_fixes"] == []
    assert any("предел витков" in note for note in out["notes"])


# --- узел fix ----------------------------------------------------------------


async def test_applied_fix_moves_the_deck_on(tmp_path: Path, manifest: TemplateManifest) -> None:
    state: DeckState = {
        "deck": deck_of(manifest, "s01"),
        "manifest": manifest,
        "selected_fixes": [finding("f1", block_id="t")],
        "fix_round": 0,
    }
    out = await fix_node(state, runtime(deps(tmp_path)))

    assert out["fix_applied"] is True
    assert out["fix_round"] == 1
    # 40 pt из шкалы синтетического шаблона ушли на ступень ниже.
    assert out["deck"].slides[0].block("t").size_pt == 24
    assert any("применено находок — 1 из 1" in note for note in out["notes"])


async def test_round_that_changed_nothing_does_not_claim_it_did(
    tmp_path: Path, manifest: TemplateManifest
) -> None:
    """Иначе граф ушёл бы на новый виток за починкой, которой не было (`route_after_fix`)."""
    state: DeckState = {
        "deck": deck_of(manifest, "s01"),
        "manifest": manifest,
        "selected_fixes": [finding("f1", AutoFix.REGENERATE_HEADLINE, block_id="t")],
        "fix_round": 0,
    }
    out = await fix_node(state, runtime(deps(tmp_path)))

    assert out["fix_applied"] is False
    assert any("не починено" in note for note in out["notes"])


def test_slide_added_by_a_fix_is_not_dropped_by_the_plan(manifest: TemplateManifest) -> None:
    """`split_slide` создаёт слайд, которого в плане нет: отбор по плану потерял бы пункты."""
    deck = deck_of(manifest, "s01", "s01-2", "s02")
    state: DeckState = {
        "plan": plan_of("s01", "s02"),
        "slides": list(deck.slides),
        "deck": deck,
        "fix_round": 1,
    }
    assert [s.slide_id for s in _ordered(state)] == ["s01", "s01-2", "s02"]


# --- деградация по бюджету ---------------------------------------------------


class FakeClient:
    model = "fake"


def test_lagging_run_switches_to_the_fast_model_and_says_so(tmp_path: Path) -> None:
    tracker = BudgetTracker()
    tracker.start()
    assert tracker.started_at is not None
    tracker.started_at -= 250
    context = deps(tmp_path, llm=FakeClient(), llm_fast=FakeClient(), budget=tracker)

    client, note = context.llm_for("compose")
    assert client is context.llm_fast
    assert note is not None and "§15" in note


def test_run_in_budget_keeps_the_main_model(tmp_path: Path) -> None:
    context = deps(tmp_path, llm=FakeClient(), llm_fast=FakeClient())
    context.budget.start()
    client, note = context.llm_for("compose")
    assert client is context.llm and note is None


def test_without_a_fast_model_there_is_nothing_to_degrade_to(tmp_path: Path) -> None:
    tracker = BudgetTracker()
    tracker.start()
    assert tracker.started_at is not None
    tracker.started_at -= STAGE_BUDGET_S["compose"] * 10
    context = deps(tmp_path, llm=FakeClient(), budget=tracker)
    client, note = context.llm_for("compose")
    assert client is context.llm and note is None


def test_missing_llm_is_an_error_not_a_silent_skip(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="требует клиента LLM"):
        deps(tmp_path).llm_for("plan")


# --- сборка графа ------------------------------------------------------------


def test_graph_has_every_node_and_the_fix_cycle() -> None:
    graph = build_graph().get_graph()
    names = {node for node in graph.nodes}
    assert {
        "parse_template",
        "ingest_content",
        "plan",
        "compose",
        "fit",
        "render",
        "audit",
        "hitl",
        "fix",
        "export",
    } <= names
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("parse_template", "plan") in edges and ("ingest_content", "plan") in edges
    assert ("fix", "fit") in edges, "цикл починки разомкнут"
    assert ("fix", "compose") not in edges, "фикс не должен перегенерировать то, что чинит"


# --- HITL: остановка и возобновление -----------------------------------------


async def test_interactive_run_stops_and_resumes_with_the_human_choice(tmp_path: Path) -> None:
    """Интерактивный прогон обязан уметь остановиться и продолжиться там же:
    на этом держится выбор фиксов в интерфейсе (change 23)."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command

    context = deps(tmp_path, interactive=True)
    graph: StateGraph[DeckState, Deps, DeckState, DeckState] = StateGraph(
        DeckState, context_schema=Deps
    )
    graph.add_node("hitl", hitl_node)
    graph.add_edge(START, "hitl")
    graph.add_edge("hitl", END)
    compiled = graph.compile(checkpointer=InMemorySaver())

    config: Any = {"configurable": {"thread_id": "t1"}}
    report = AuditReport(deck_id="d1", variant="A", findings=[finding("f1"), finding("f2")])
    stopped = await compiled.ainvoke(
        {"audit": report, "fix_round": 0}, config=config, context=context
    )
    assert "__interrupt__" in stopped, "граф не остановился и спрашивать было некого"

    resumed = await compiled.ainvoke(Command(resume=["f2"]), config=config, context=context)
    assert [f.finding_id for f in resumed["selected_fixes"]] == ["f2"]
