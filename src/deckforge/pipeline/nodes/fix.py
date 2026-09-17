"""Узел `fix`. Change (17) `pipeline-orchestration`.

Виток починки ведёт в `fit`, а не в `compose`, хотя ARCHITECTURE.md §3 рисует стрелку
в композицию. Причина в контракте `FixApplier` (change 19): он возвращает **готовый**
`DeckIR`. Повторная композиция сходила бы в модель заново и выбросила бы только что
применённый фикс — чинить и тут же перегенерировать чинимое бессмысленно. Заново
проходятся вписывание, запись и аудит: только они видят последствия правки.

Пока change (19) не приехал, `FixApplier` поднимает `NotImplementedError`. Узел пишет
это в `errors` и ведёт колоду на экспорт: граф замкнут, и когда фиксы появятся,
править в нём будет нечего.
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
        try:
            deck, _report = await asyncio.to_thread(
                partial(FixApplier().apply, state["deck"], selected, state["manifest"])
            )
        except NotImplementedError:
            return {
                "fix_round": round_no,
                "fix_applied": False,
                "selected_fixes": [],
                "stage_timings_s": timings,
                "errors": [
                    f"авто-фиксы не применены ({len(selected)} находок): "
                    "change (19) audit-remediation ещё не реализован"
                ],
            }

    return {
        "deck": deck,
        "slides": list(deck.slides),
        "fix_round": round_no,
        "fix_applied": True,
        "selected_fixes": [],
        "stage_timings_s": timings,
        "notes": [f"виток починки {round_no}: применено находок — {len(selected)}"],
    }
