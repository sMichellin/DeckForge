"""Узел `assign` в графе. Change `the-assign-node` (план Б, 2п; ADR-009).

Пример выбирается до текста: на пути `by_example` между `plan` и `compose` стоит `assign`,
который строит паспорта и назначает примеры на всю колоду. Путь `legacy` узел обходит.
Узел проверяется на фикстуре настоящего прогона 28.09 — без модели и без стенда.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest
from langgraph.runtime import Runtime

from deckforge.config import RunConfig
from deckforge.domain.content import Brief
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.graph import build_graph, route_after_plan
from deckforge.pipeline.nodes.assign import assign_node
from deckforge.pipeline.replay import from_fixture
from deckforge.pipeline.run import RunResult

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-28" / "vk-tech"


@pytest.mark.parametrize(
    ("state", "route"),
    [({"composition_path": "by_example"}, "assign"),
     ({"composition_path": "legacy"}, "compose"),
     ({}, "compose")],
    ids=["by_example", "legacy", "old-checkpoint"],
)
def test_only_by_example_goes_through_assign(state: dict[str, str], route: str) -> None:
    """Норма: `by_example` — через `assign`; `legacy` и старый чекпойнт — сразу в `compose`."""
    assert route_after_plan(state) == route  # type: ignore[arg-type]


def test_the_graph_has_the_assign_node() -> None:
    assert "assign" in build_graph().get_graph().nodes


@pytest.fixture(scope="module")
def assigned(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    run = from_fixture(FIXTURE)
    deps = Deps(
        brief=Brief(purpose="report", audience="правление"),
        run=RunConfig(),
        out_dir=tmp_path_factory.mktemp("out"),
        fonts=FontLibrary.default(),
    )
    state = {
        "plan": run.plan, "manifest": run.manifest, "design_system": run.design_system,
        "seed": 1341, "composition_path": "by_example",
    }
    return asyncio.run(assign_node(state, Runtime(context=deps)))  # type: ignore[arg-type]


def test_every_planned_slide_gets_an_assignment(assigned: dict[str, object]) -> None:
    """Норма: назначение на каждый слайд плана, в порядке плана."""
    plan = from_fixture(FIXTURE).plan
    ids = [a.slide_id for a in assigned["assignments"]]  # type: ignore[attr-defined]

    assert ids == [slide.slide_id for slide in plan.slides]


def test_the_design_system_leaves_with_passports(assigned: dict[str, object]) -> None:
    """Норма: дальше по графу идёт дизайн-система с паспортами — по ней пишут и верстают."""
    recipes = assigned["design_system"].recipes  # type: ignore[attr-defined]

    assert sum(1 for r in recipes if r.passport is not None) >= len(recipes) // 2


def test_no_example_repeats_on_the_28_09_plan(assigned: dict[str, object]) -> None:
    """Строка 2 приёмки на плане VK Tech 28.09: не больше двух раз и не подряд (было 6 и 3)."""
    chosen = [a.recipe_id for a in assigned["assignments"]]  # type: ignore[attr-defined]
    uses = Counter(r for r in chosen if r)

    assert max(uses.values()) <= 2
    assert not any(left and left == right for left, right in pairwise(chosen))


def test_the_node_says_what_it_did(assigned: dict[str, object]) -> None:
    """Норма: заметки называют число паспортов и сколько слайдов идут без примера."""
    notes = " ".join(assigned["notes"])  # type: ignore[arg-type]

    assert "паспорт у" in notes and "путём дизайн-системы" in notes
    assert "assign" in assigned["stage_timings_s"]  # type: ignore[operator]


def test_the_run_report_lists_the_assignments(
    assigned: dict[str, object], tmp_path: Path
) -> None:
    """Норма: `run.json` несёт назначения — пример или его отсутствие и причину."""
    result = RunResult(variant="A", run_id="r1", out_dir=tmp_path,
                       state={"assignments": assigned["assignments"]})  # type: ignore[typeddict-item]

    rows = result.report()["assignments"]

    assert len(rows) == 10 and all(row["reason"] for row in rows)
