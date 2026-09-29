"""Строки 6б, 8 и 9 мерила плана Б. Change `the-eye-rows-are-measured` (круг 2).

На первом живом прогоне `by_example` строки 1–7 были зелёными, а глазами на слайдах было
видно три беды, которых они не считали: слова, оборванные посреди, выдуманные числа,
слайды без содержания (`docs/agents/tasks-plan-b-round-2.md`). Теперь они — строки мерила,
по находкам проверок потока C в `run.json`, с прочерком, если проверка не шла.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from deckforge.domain.audit import AuditReport, AuditSummary, Finding
from deckforge.domain.enums import Severity
from deckforge.pipeline.run import RunResult

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "runs" / "2026-09-29"
NUMBERS = "content.numbers_grounded"
LOST = ("integrity.content_lost", "integrity.empty_slide")
WORD_CUT = "content.word_cut"
ALL = [NUMBERS, *LOST, WORD_CUT]


@pytest.fixture(scope="module")
def plan_b() -> ModuleType:
    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        return importlib.import_module("plan_b_metrics")
    finally:
        sys.path.remove(str(scripts))


def number(slide_id: str, value: str, *, evidence: bool = True) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "check_id": NUMBERS, "slide_id": slide_id, "severity": "error",
        "message": f"Числа «{value}» нет в исходных материалах",
    }
    if evidence:
        finding["evidence"] = {"raw": value, "value": value, "unit": "—"}
    return finding


def test_one_invented_number_on_a_slide_is_one(plan_b: ModuleType) -> None:
    """Нарушитель: «1» шесть раз на одном слайде — одно выдуманное число, а не шесть
    (VK Tech 29.09 s06, подписи шкалы `ex052`); другое число или другой слайд — ещё одно."""
    report = {"checks_known": ALL, "findings_detail": [
        *[number("s06", "1") for _ in range(6)], number("s06", "100%"), number("s08", "1"),
    ]}

    assert plan_b.deck_metrics(report).invented_numbers == 3


def test_without_evidence_the_number_comes_from_the_message(plan_b: ModuleType) -> None:
    """Норма: у отчёта до поля `evidence` число берётся из сообщения — счёт тот же."""
    report = {"checks_known": ALL, "findings_detail": [
        number("s06", "1", evidence=False), number("s06", "1", evidence=False),
        number("s09", "1341", evidence=False),
    ]}

    assert plan_b.deck_metrics(report).invented_numbers == 2


def test_a_slide_lost_twice_is_one_slide(plan_b: ModuleType) -> None:
    """Нарушитель: обе проверки строки 9 на одном слайде — один потерянный слайд."""
    report = {"checks_known": ALL, "findings_detail": [
        {"check_id": LOST[0], "slide_id": "s10"}, {"check_id": LOST[1], "slide_id": "s10"},
        {"check_id": LOST[0], "slide_id": "s01"},
    ]}

    assert plan_b.deck_metrics(report).lost_slides == 2


def test_a_run_without_the_check_gives_a_dash(plan_b: ModuleType) -> None:
    """Норма: код прогона проверки не знал — прочерк, а не ноль: «не мерили» — не «чисто»."""
    metrics = plan_b.deck_metrics({"checks_known": [NUMBERS], "findings_detail": []})

    assert metrics.invented_numbers == 0
    assert metrics.lost_slides is None and metrics.word_cuts is None
    assert "| 6б | Текстов, оборванных посреди слова | — |" in plan_b.table([metrics])


def test_the_rows_on_the_fixtures_of_29_09(plan_b: ModuleType) -> None:
    """Мерило на живом прогоне 29.09 (`c8ea32e`): строки, которые до круга 2 видели только
    глазами. Строка 8 — 6 / 3 / 1 (VK Tech 11 находок — это 3 числа: «1» на s06 и s08,
    «100%» на s09); строка 9 — WorkSpace s10, Education s10; строки 6б на этом коде нет."""
    decks = {
        name: plan_b.deck_metrics(plan_b.load_report(FIXTURES / name))
        for name in ("workspace", "vk-tech", "education")
    }

    assert {n: d.invented_numbers for n, d in decks.items()} == {
        "workspace": 6, "vk-tech": 3, "education": 1,
    }
    assert {n: d.lost_slides for n, d in decks.items()} == {
        "workspace": 1, "vk-tech": 0, "education": 1,
    }
    assert {d.word_cuts for d in decks.values()} == {None}


def test_the_run_report_carries_the_evidence(tmp_path: Path) -> None:
    """Норма: `findings_detail` несёт `evidence` находки — по нему строка 8 считает числа."""
    finding = Finding(
        finding_id="f1", check_id=NUMBERS, deterministic=True, severity=Severity.ERROR,
        slide_id="s06", message="Числа «1» нет", evidence={"raw": "1", "value": "1", "unit": "—"},
    )
    audit = AuditReport(deck_id="d", variant="A", findings=[finding],
                        summary=AuditSummary(errors=1))
    report = RunResult(variant="A", run_id="r", out_dir=tmp_path,
                       state={"audit": audit}).report()  # type: ignore[typeddict-item]

    (detail,) = report["findings_detail"]
    assert detail["evidence"] == {"raw": "1", "value": "1", "unit": "—"}
