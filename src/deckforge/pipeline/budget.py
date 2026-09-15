"""Бюджет времени по стадиям (C5, §12). Change (17).

Превышение бюджета — не исключение, а сигнал деградации: `llm_main` → `llm_fast`,
VLM-аудит на выборке слайдов вместо всех.
"""

from __future__ import annotations

from dataclasses import dataclass

STAGE_BUDGET_S: dict[str, int] = {
    "parse_template": 25,
    "ingest_content": 15,
    "plan": 35,
    "compose": 100,
    "render": 40,
    "audit": 60,
    "export": 25,
}
TOTAL_BUDGET_S = 300


@dataclass(slots=True)
class BudgetTracker:
    total_budget_s: int = TOTAL_BUDGET_S

    def over_budget(self, timings: dict[str, float]) -> list[str]:
        return [stage for stage, t in timings.items() if t > STAGE_BUDGET_S.get(stage, 10**9)]
