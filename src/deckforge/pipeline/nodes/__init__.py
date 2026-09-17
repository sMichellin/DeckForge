"""Узлы графа: тонкие обёртки над слоями. Change (17).

В узле нет ни одного решения о содержании колоды — только вызов сервиса слоя, замер
времени и запись результата в состояние (ADR-006). Всё, что похоже на бизнес-логику,
живёт в слое и покрыто его тестами.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from deckforge.pipeline.deps import Deps


@asynccontextmanager
async def timed(deps: Deps, stage: str) -> AsyncIterator[dict[str, float]]:
    """Замер стадии. Отданный словарь заполняется на выходе из блока.

    Часы бюджета запускаются первым же узлом, а не созданием `Deps`: между сборкой
    зависимостей и стартом графа может пройти сколько угодно времени, и расписание
    §12 считалось бы от неверной точки.
    """
    deps.budget.start()
    started = time.perf_counter()
    timings: dict[str, float] = {}
    try:
        yield timings
    finally:
        seconds = time.perf_counter() - started
        deps.budget.record(stage, seconds)
        timings[stage] = round(seconds, 3)
