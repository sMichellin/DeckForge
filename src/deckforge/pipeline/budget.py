"""Бюджет времени по стадиям (C5, §12). Change (17).

Превышение бюджета — не исключение, а сигнал деградации: `llm_main` → `llm_fast`,
аудит без VLM, превью не рендерятся.

Бюджет здесь — **расписание, а не отчёт**. Вопрос, на который отвечает трекер, звучит
не «уложились ли мы», а «хватит ли остатка на всё, что впереди»: узнать о превышении
после экспорта поздно, рычаг деградации к этому моменту дёргать уже не по чему.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

#: Плановое распределение из ARCHITECTURE.md §12. Сумма равна `TOTAL_BUDGET_S`.
STAGE_BUDGET_S: dict[str, int] = {
    "parse_template": 25,
    "ingest_content": 15,
    "plan": 35,
    "compose": 100,
    "fit": 10,
    "render": 30,
    "audit": 60,
    "export": 25,
}
TOTAL_BUDGET_S = 300

#: Порядок прохождения стадий. Нужен расписанию: «что впереди» определяется им.
STAGE_ORDER: tuple[str, ...] = (
    "parse_template",
    "ingest_content",
    "plan",
    "compose",
    "fit",
    "render",
    "audit",
    "export",
)

#: Стадии, идущие параллельно предыдущей. В расписание по стенным часам их бюджет
#: не добавляется: ingestion контента считается одновременно с парсингом шаблона.
PARALLEL_STAGES = frozenset({"ingest_content"})


def schedule_from(stage: str) -> int:
    """Сколько секунд по плану осталось потратить, начиная со стадии `stage`."""
    if stage not in STAGE_ORDER:
        return 0
    start = STAGE_ORDER.index(stage)
    return sum(
        STAGE_BUDGET_S[name]
        for name in STAGE_ORDER[start:]
        if name not in PARALLEL_STAGES
    )


@dataclass(slots=True)
class BudgetTracker:
    """Часы прогона. Один экземпляр на прогон графа, живёт в `Deps`."""

    total_budget_s: int = TOTAL_BUDGET_S
    started_at: float | None = None
    timings: dict[str, float] = field(default_factory=dict)

    def start(self) -> None:
        """Отсчёт идёт от первого узла, а не от создания трекера."""
        if self.started_at is None:
            self.started_at = time.perf_counter()

    @property
    def elapsed_s(self) -> float:
        if self.started_at is None:
            return 0.0
        return time.perf_counter() - self.started_at

    @property
    def remaining_s(self) -> float:
        return self.total_budget_s - self.elapsed_s

    def record(self, stage: str, seconds: float) -> None:
        self.timings[stage] = round(seconds, 3)

    def behind_schedule(self, stage: str) -> bool:
        """Остатка не хватает на `stage` и всё, что за ней."""
        return self.remaining_s < schedule_from(stage)

    def over_budget(self, timings: dict[str, float] | None = None) -> list[str]:
        """Стадии, которые вышли за свой бюджет. Отчёт, а не решение."""
        measured = self.timings if timings is None else timings
        return sorted(
            stage for stage, t in measured.items() if t > STAGE_BUDGET_S.get(stage, 10**9)
        )
