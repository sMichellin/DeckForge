"""C5: колода 10–15 слайдов за ≤ 300 с. Change (17), критерий гейта 20.09 (PLAN.md).

Тест намеренно заведён пустым уже сейчас: он должен покраснеть в тот день, когда
пайплайн заработает и не уложится в бюджет, а не появиться постфактум.
"""

from __future__ import annotations

import pytest

TOTAL_BUDGET_S = 300


@pytest.mark.slow
@pytest.mark.needs_llm
@pytest.mark.skip(reason="change (17) pipeline-orchestration")
def test_deck_generated_within_budget() -> None:
    raise NotImplementedError
