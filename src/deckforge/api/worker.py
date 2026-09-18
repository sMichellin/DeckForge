"""arq-воркер: долгая генерация вне HTTP-запроса. Change (23) `service-api`.

Файл тонкий намеренно: сама работа живёт в `jobs.py` и зовётся оттуда же и тестами,
и inline-режимом. Здесь только привязка к arq — имена задач, число одновременных
прогонов и время, после которого задача считается зависшей.

Имена функций обязаны совпадать с константами `queue.py`: очередь кладёт в Redis имя,
а не ссылку, и разошедшееся имя означает задачу, которую никто не возьмёт. За этим
следит `tests/unit/test_api_service.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from arq.connections import RedisSettings

from deckforge.api import jobs
from deckforge.api.store import RunStore
from deckforge.config import get_settings


def store() -> RunStore:
    return RunStore(Path(get_settings().artifacts_dir) / "runs")


async def deckforge_run(_: dict[str, Any], run_id: str) -> dict[str, Any]:
    return await jobs.run_job(run_id, store())


async def deckforge_resume(_: dict[str, Any], run_id: str, selected: list[str]) -> dict[str, Any]:
    return await jobs.resume_job(run_id, store(), list(selected))


class WorkerSettings:
    """Настройки arq."""

    functions: ClassVar[list[Any]] = [deckforge_run, deckforge_resume]
    #: Два прогона на воркер: каждый держит свой LibreOffice и свой чекпойнт, и третий
    #: на типичной машине упирается в память рендера, а не в процессор.
    max_jobs = 2
    #: Прогон по бюджету §12 идёт пять минут; час — это «задача повисла», а не «долго идёт».
    job_timeout = 3600
    keep_result = 3600
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
