"""Строка 3 мерила плана Б — пустые карточки. Change `the-third-row-is-measured`.

Считается по находкам `integrity.empty_group` (поток C, #255) в `run.json`. Прогон, собранный
кодом без этой проверки, обязан дать прочерк, а не ноль — для этого отчёт перечисляет
проверки, известные его коду (`checks_known`).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from deckforge.pipeline.run import RunResult

ROOT = Path(__file__).resolve().parents[2]
CHECK = "integrity.empty_group"


@pytest.fixture(scope="module")
def plan_b() -> ModuleType:
    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        return importlib.import_module("plan_b_metrics")
    finally:
        sys.path.remove(str(scripts))


def finding(slide_id: str) -> dict[str, Any]:
    return {"check_id": CHECK, "slide_id": slide_id, "severity": "warning"}


def test_slides_with_an_empty_card_are_counted_once(plan_b: ModuleType) -> None:
    """Нарушитель: три пустые группы на двух слайдах — два слайда."""
    report = {"checks_known": [CHECK], "skipped_checks": [],
              "findings_detail": [finding("s02"), finding("s02"), finding("s05")]}

    assert plan_b.deck_metrics(report).empty_cards == 2


def test_a_clean_run_with_the_check_is_zero(plan_b: ModuleType) -> None:
    """Норма: проверка шла, находок нет — ноль."""
    assert plan_b.deck_metrics({"checks_known": [CHECK]}).empty_cards == 0


@pytest.mark.parametrize(
    "report",
    [{}, {"checks_known": [CHECK], "skipped_checks": [CHECK]}],
    ids=["code-without-the-check", "check-skipped"],
)
def test_not_measured_is_not_zero(plan_b: ModuleType, report: dict[str, Any]) -> None:
    """Норма: проверки не было в коде прогона или она пропущена — прочерк, а не ноль."""
    assert plan_b.deck_metrics(report).empty_cards is None


def test_the_run_report_lists_the_checks_its_code_knows(tmp_path: Path) -> None:
    """Норма: `run.json` перечисляет проверки своего кода, среди них — проверка строки 3."""
    known = RunResult(variant="A", run_id="r", out_dir=tmp_path, state={}).report()["checks_known"]

    assert CHECK in known and known == sorted(known)
