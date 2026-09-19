"""Сервисы прогона. Change (17) `pipeline-orchestration`.

Всё, что узлу нужно и чего нельзя положить в состояние: клиенты инференса, судья,
каталог шрифтов, конфиг запуска, часы бюджета. Состояние уезжает в чекпойнт sqlite —
открытый HTTP-клиент туда не сериализуется, а без чекпойнта не работает HITL.

LangGraph доставляет этот объект узлу как `runtime.context`, не примешивая его к данным.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deckforge.config import RunConfig
from deckforge.domain.content import Brief
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.budget import BudgetTracker


class PipelineError(RuntimeError):
    """Прогон невозможен: не хватает того, без чего колоды не будет."""


@dataclass
class Deps:
    """Контекст прогона. Один экземпляр на один вариант вёрстки."""

    brief: Brief
    run: RunConfig
    out_dir: Path

    #: Клиент для плана и композиции. `None` — только для тестов слоя без модели.
    llm: Any | None = None
    #: Дешёвая модель для рычага деградации §15. Нет — деградировать нечем.
    llm_fast: Any | None = None
    #: Судья VLM для смыслового аудита (change 18). Нет — аудит детерминированный.
    vlm: Any | None = None
    #: VLM для классификации макетов (change 5). Нет — работает одна эвристика.
    layout_vlm: Any | None = None

    fonts: FontLibrary | None = None
    cache_dir: Path | None = None
    asset_dir: Path | None = None
    #: Куда класть превью и промежуточные файлы прогона.
    work_dir: Path | None = None

    budget: BudgetTracker = field(default_factory=BudgetTracker)
    prompt_profile: str | None = None

    #: HITL останавливает граф только там, где есть кому ответить. В пакетном прогоне
    #: выбор фиксов делается по конфигу, а не ожиданием, которого никто не прервёт.
    interactive: bool = False

    _semaphore: asyncio.Semaphore | None = field(default=None, repr=False)

    def slots(self) -> asyncio.Semaphore:
        """Ограничитель параллельной композиции (`parallel_slides`, §12)."""
        if self._semaphore is None:
            # Параллельность прогона не может быть выше той, что держит бэкенд: лишние
            # запросы ждали бы в его очереди, и ожидание съедало бы таймаут вызова.
            spec = getattr(self.llm, "spec", None)
            backend = getattr(spec, "max_concurrency", None) or self.run.parallel_slides
            self._semaphore = asyncio.Semaphore(max(1, min(self.run.parallel_slides, backend)))
        return self._semaphore

    def llm_for(self, stage: str) -> tuple[Any, str | None]:
        """Клиент для стадии и причина деградации, если рычаг §15 сработал.

        Возвращается парой, а не подменяется молча: разменянное качество обязано
        попасть в отчёт прогона.
        """
        if self.llm is None:
            raise PipelineError(
                f"стадия {stage!r} требует клиента LLM: он не собран "
                "(проверьте configs/models.yaml и переменные окружения)"
            )
        if (
            self.llm_fast is not None
            and self.llm_fast is not self.llm
            and self.budget.behind_schedule(stage)
        ):
            return self.llm_fast, (
                f"{stage}: остатка бюджета не хватает на расписание — "
                "основная модель заменена быстрой (§15)"
            )
        return self.llm, None

    def previews_dir(self) -> Path:
        base = self.work_dir or self.out_dir
        path = base / "previews"
        path.mkdir(parents=True, exist_ok=True)
        return path
