"""Очередь долгих задач. Change (23) `service-api`.

Через очередь ходит одно короткое сообщение — «начни этот прогон» либо «продолжи его
с таким выбором». Данные прогона лежат в `RunStore`: очередь их не переносит и потому
не становится вторым источником истины.

Реализации две, и вторая — не костыль для тестов.

* `ArqQueue` — рабочий путь: воркер живёт отдельным контейнером, потому что рендер
  превью запускает `soffice` подпроцессом (`docker/compose.yaml`).
* `InlineQueue` — тот же прогон в процессе приложения, без Redis и без воркера.
  Нужен там, где лишний движущийся узел дороже изоляции: на записи демо (A4) и при
  разборе прогона руками. Про ограничения сказано в самом классе.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from deckforge.api.store import RunStore

RUN_JOB = "deckforge_run"
RESUME_JOB = "deckforge_resume"


class Queue(Protocol):
    """Что нужно приложению от очереди и ничего сверх."""

    async def submit(self, job: str, run_id: str, *args: Any) -> None: ...

    async def close(self) -> None: ...


@dataclass(slots=True)
class InlineQueue:
    """Прогон в процессе приложения.

    **Чего он не даёт.** Задача живёт в цикле событий веб-приложения: перезапуск
    процесса её убивает, а параллельные прогоны делят один цикл. Для одного человека
    за одним прогоном — ровно то, что нужно; для нескольких одновременно нужен `ArqQueue`.

    Ссылки на задачи держатся намеренно: без них сборщик мусора вправе забрать
    задачу целиком, и прогон оборвётся посреди стадии без единого сообщения.
    """

    store: RunStore
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    async def submit(self, job: str, run_id: str, *args: Any) -> None:
        from deckforge.api import jobs

        if job == RUN_JOB:
            coro = jobs.run_job(run_id, self.store)
        elif job == RESUME_JOB:
            coro = jobs.resume_job(run_id, self.store, list(args[0]) if args else [])
        else:  # pragma: no cover — имена задач заведены здесь же
            raise ValueError(f"неизвестная задача {job!r}")

        task = asyncio.create_task(coro, name=f"{job}:{run_id}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()


@dataclass(slots=True)
class ArqQueue:
    """Очередь arq поверх Redis. Пул один на приложение, а не на запрос."""

    redis_url: str
    _pool: Any | None = None

    async def submit(self, job: str, run_id: str, *args: Any) -> None:
        pool = await self._ensure_pool()
        await pool.enqueue_job(job, run_id, *args)

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            from arq.connections import RedisSettings, create_pool

            self._pool = await create_pool(RedisSettings.from_dsn(self.redis_url))
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
