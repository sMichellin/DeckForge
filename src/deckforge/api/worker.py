"""arq-воркер: долгая генерация вне HTTP-запроса. Change (23) `service-api`."""

from __future__ import annotations

from typing import ClassVar


class WorkerSettings:
    functions: ClassVar[list[object]] = []
    max_jobs = 2
