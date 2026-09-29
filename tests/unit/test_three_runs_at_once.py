"""Три прогона одновременно. Change `three-runs-at-once` (план Б, круг 3, тимлид).

«Все варианты сразу» ставит три прогона; воркер обязан вести все три, а не два с третьим
в очереди. Число задаётся переменной окружения, по умолчанию — три.
"""

from __future__ import annotations

import pytest

from deckforge.api.worker import WorkerSettings
from deckforge.config import Settings
from deckforge.registry.variants import load_variant_profiles


def test_the_worker_takes_every_variant_at_once() -> None:
    """Норма: одновременных прогонов не меньше, чем вариантов вёрстки."""
    assert WorkerSettings.max_jobs >= len(load_variant_profiles())


def test_the_default_is_three() -> None:
    """Норма: без переменной — три, по числу вариантов A, B, C."""
    assert Settings().worker_max_jobs == 3


def test_a_small_machine_lowers_it_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нарушитель прежнего вида: число было зашито в код, теперь снижается переменной."""
    monkeypatch.setenv("DECKFORGE_WORKER_MAX_JOBS", "1")
    assert Settings().worker_max_jobs == 1
