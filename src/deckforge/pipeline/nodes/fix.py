"""Узел `fix`. Change (17) `pipeline-orchestration`, подключение фиксов — change (19).

Виток починки ведёт в `fit`, а не в `compose`, хотя ARCHITECTURE.md §3 рисует стрелку
в композицию. Причина в контракте `FixApplier` (change 19): он возвращает **готовый**
`DeckIR`. Повторная композиция сходила бы в модель заново и выбросила бы только что
применённый фикс — чинить и тут же перегенерировать чинимое бессмысленно. Заново
проходятся вписывание, запись и аудит: только они видят последствия правки.

`FixApplier` не падает на находке, которую чинить нечем: отказ приезжает флагом
`auto_fix_applied` и причиной в `evidence`. Поэтому узел смотрит на флаги, а не на то,
что вызов вернулся без исключения. Виток, не изменивший ни одного слайда, обязан вести
на экспорт: иначе граф крутил бы витки до предела впустую (`route_after_fix`).
"""

from __future__ import annotations

import asyncio
from functools import partial

from langgraph.runtime import Runtime

from deckforge.audit.fixes import FixApplier
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState


async def fix_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """Применяет выбранные фиксы к `DeckIR` (change 19)."""
    deps = runtime.context
    selected = state.get("selected_fixes") or []
    round_no = state.get("fix_round", 0) + 1

    async with timed(deps, "fix") as timings:
        deck, report = await asyncio.to_thread(
            partial(FixApplier().apply, state["deck"], selected, state["manifest"])
        )

    applied = [f for f in report.findings if f.auto_fix_applied]
    # Отказ виден пользователю поимённо: «применено 2 из 5» без причин оставшихся трёх
    # выглядит как сбой, хотя это законный исход (шкала кончилась, чинит модель).
    refused = [
        f"не починено {f.check_id} на {f.slide_id}: "
        + f.evidence.get("fix_skipped", "причина не указана")
        for f in report.findings
        if not f.auto_fix_applied
    ]

    return {
        "deck": deck,
        "slides": list(deck.slides),
        "fix_round": round_no,
        "fix_applied": bool(applied),
        "selected_fixes": [],
        "stage_timings_s": timings,
        "notes": [
            f"виток починки {round_no}: применено находок — {len(applied)} из {len(selected)}",
            *refused,
        ],
    }
