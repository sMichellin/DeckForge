"""Бюджет времени как расписание. Change (17) `pipeline-orchestration`.

Проверяется не «уложились ли», а то, что трекер умеет ответить на вопрос «хватит ли
остатка на всё, что впереди» — от этого ответа зависят рычаги деградации §15.
"""

from __future__ import annotations

from deckforge.pipeline.budget import (
    PARALLEL_STAGES,
    STAGE_BUDGET_S,
    STAGE_ORDER,
    TOTAL_BUDGET_S,
    BudgetTracker,
    schedule_from,
)


def test_stage_budgets_add_up_to_the_total() -> None:
    """§12: сумма стадий равна SLA. Разошлись — расписание врёт на каждом шаге."""
    assert sum(STAGE_BUDGET_S.values()) == TOTAL_BUDGET_S


def test_every_stage_has_a_place_in_the_order() -> None:
    assert set(STAGE_ORDER) == set(STAGE_BUDGET_S)


def test_schedule_shrinks_towards_the_end() -> None:
    previous = schedule_from(STAGE_ORDER[0])
    for stage in STAGE_ORDER[1:]:
        current = schedule_from(stage)
        assert current <= previous
        previous = current
    assert schedule_from("export") == STAGE_BUDGET_S["export"]


def test_parallel_stage_does_not_add_wall_clock_time() -> None:
    """Ingestion идёт одновременно с парсингом: в расписание по стенным часам
    его бюджет не входит, иначе рычаг срабатывал бы раньше времени."""
    assert "ingest_content" in PARALLEL_STAGES
    assert schedule_from("parse_template") == TOTAL_BUDGET_S - STAGE_BUDGET_S["ingest_content"]


def test_unknown_stage_does_not_reserve_anything() -> None:
    """Узел `fix` в расписании §12 не объявлен: виток починки не планируется заранее."""
    assert schedule_from("fix") == 0


def test_tracker_is_not_behind_schedule_at_the_start() -> None:
    tracker = BudgetTracker()
    tracker.start()
    assert not tracker.behind_schedule("parse_template")


def test_tracker_is_behind_schedule_when_the_remainder_is_too_small() -> None:
    tracker = BudgetTracker(total_budget_s=TOTAL_BUDGET_S)
    # Эмуляция «прошло 250 с»: часы трекера — perf_counter, сдвигаем точку старта.
    tracker.start()
    assert tracker.started_at is not None
    tracker.started_at -= 250
    assert tracker.behind_schedule("compose")
    assert tracker.remaining_s < STAGE_BUDGET_S["compose"]


def test_clock_starts_once_and_not_on_construction() -> None:
    tracker = BudgetTracker()
    assert tracker.elapsed_s == 0.0
    tracker.start()
    first = tracker.started_at
    tracker.start()
    assert tracker.started_at == first


def test_over_budget_names_only_the_stages_that_overran() -> None:
    tracker = BudgetTracker()
    tracker.record("plan", STAGE_BUDGET_S["plan"] + 1)
    tracker.record("export", 1.0)
    assert tracker.over_budget() == ["plan"]
