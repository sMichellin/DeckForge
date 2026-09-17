"""Узел `hitl`. Change (17) `pipeline-orchestration`.

Единственный узел, который умеет останавливать граф. В интерактивном режиме он зовёт
`interrupt()` и ждёт выбора человека: чекпойнт sqlite позволяет возобновить прогон
в другом процессе — это и нужно API потока C (change 23).

В пакетном прогоне ждать некому, поэтому выбор делает конфиг: чинятся только находки
с объявленным `auto_fix`, и не больше `max_fix_rounds` витков. Молчаливого «починим
всё» здесь нет — что выбрано, видно в отчёте прогона.
"""

from __future__ import annotations

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from deckforge.domain.audit import Finding
from deckforge.domain.enums import AutoFix
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.state import DeckState

DEFAULT_MAX_FIX_ROUNDS = 2


def fixable(findings: list[Finding]) -> list[Finding]:
    """Находки, для которых объявлен авто-фикс (§5.3)."""
    return [f for f in findings if f.auto_fix is not AutoFix.NONE and not f.auto_fix_applied]


async def hitl_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """Выбор, что чинить: человеком или конфигом."""
    deps = runtime.context
    report = state.get("audit")
    findings = list(report.findings) if report is not None else []
    candidates = fixable(findings)

    rounds = int(deps.run.audit.get("max_fix_rounds", DEFAULT_MAX_FIX_ROUNDS))
    done = state.get("fix_round", 0)
    if done >= rounds or not candidates:
        note = (
            [f"hitl: предел витков починки ({rounds}) исчерпан"]
            if candidates and done >= rounds
            else []
        )
        return {"selected_fixes": [], "notes": note}

    if deps.interactive:
        chosen = interrupt(
            {
                "reason": "audit",
                "deck_id": report.deck_id if report is not None else state.get("run_id"),
                "fix_round": done,
                "findings": [f.model_dump(mode="json") for f in candidates],
            }
        )
        wanted = {str(item) for item in (chosen or [])}
        selected = [f for f in candidates if f.finding_id in wanted]
    elif deps.run.audit.get("auto_fix", True):
        selected = candidates
    else:
        selected = []

    return {"selected_fixes": selected}
