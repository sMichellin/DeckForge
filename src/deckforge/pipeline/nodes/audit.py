"""Узел `audit`. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from typing import Any

from langgraph.runtime import Runtime

from deckforge.audit.deterministic.design import slide_metrics
from deckforge.audit.runner import AuditRunner
from deckforge.config import get_settings
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState

#: Ключи `audit:` профиля, которые управляют графом, а не проверками. Всё остальное —
#: пороги, и они едут в `ctx.params`: иначе `vlm_votes: 1` в профиле `demo` (ради
#: предсказуемого времени на видео) до судьи не доезжает и аудит стоит втрое дороже.
PIPELINE_KEYS = frozenset({"run_deterministic", "run_semantic", "auto_fix", "max_fix_rounds"})


def check_params(audit: dict[str, Any]) -> dict[str, Any]:
    """Пороги прогона из профиля — всё, что не управляет графом."""
    return {key: value for key, value in audit.items() if key not in PIPELINE_KEYS}


def run_params(audit: dict[str, Any], languagetool_url: str) -> dict[str, Any]:
    """Параметры прогона для проверок: адреса окружения плюс пороги профиля.

    `DECKFORGE_LANGUAGETOOL_URL` была объявлена в настройках и не читалась нигде —
    проверка орфографии брала адрес только из `server_url` в `audit_checks.yaml`,
    а там его нет. Адрес — свойство окружения, а не порог проверки, поэтому он идёт
    отсюда. Профиль, если задаст `server_url` явно, главнее.

    Подавать адрес безопасно и тогда, когда сервиса нет: клиент падает сразу при
    создании, и проверка уходит в пропущенные, а не рвёт аудит посреди слайдов.
    """
    return {"server_url": languagetool_url, **check_params(audit)}


DESIGN_CHECK = "design.ink_balance"


def _design_tolerances(audit: dict[str, Any]) -> dict[str, float]:
    """Допуски дисбаланса — те же, что у проверки: метрика в отчёте и в находке одна.

    Порядок тот же, что в `AuditRunner`: порог проверки из `audit_checks.yaml` главнее
    профиля прогона. Иначе отчёт и находка мерили бы одно разными линейками.
    """
    from deckforge.registry import load_check_specs

    spec = load_check_specs().by_id(DESIGN_CHECK)
    params = {**check_params(audit), **(dict(spec.params) if spec is not None else {})}
    return {
        name: float(value)
        for name in ("x_tol", "y_tol")
        if isinstance(value := params.get(name), int | float)
    }


def _read_examples(paths: list[Path]) -> list[bytes]:
    """Картинки слайдов-примеров; пропавший файл пропускается, а не роняет аудит."""
    return [path.read_bytes() for path in paths if path.is_file()]


def _read_previews(previews: dict[str, Path]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for slide_id, path in previews.items():
        if path.is_file():
            out[slide_id] = path.read_bytes()
    return out


async def audit_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """Детерминированные проверки и VLM-судья по готовой колоде (changes 15, 18)."""
    deps = runtime.context
    previews = state.get("previews") or {}
    layout_previews = state.get("layout_previews") or {}
    example_paths = list(state.get("example_previews") or [])

    degradations: list[str] = []
    vlm = deps.vlm if deps.run.audit.get("run_semantic", True) else None
    if vlm is not None and deps.budget.behind_schedule("audit"):
        # Рычаг §15: смысловой аудит — самая дорогая стадия, а 25 детерминированных
        # проверок остаются на месте и стоят миллисекунды.
        vlm = None
        degradations.append("audit: смысловой аудит выключен — остатка бюджета не хватает (§15)")

    runner = AuditRunner(run_params=run_params(deps.run.audit, get_settings().languagetool_url))
    async with timed(deps, "audit") as timings:
        pngs = await asyncio.to_thread(_read_previews, previews)
        chrome = await asyncio.to_thread(_read_previews, layout_previews)
        report = await runner.run(
            state["deck"],
            state["manifest"],
            state["content"],
            previews=pngs,
            layout_previews=chrome,
            example_previews=await asyncio.to_thread(_read_examples, example_paths),
            deck_path=state.get("pptx_path"),
            vlm=vlm,
        )
        # Метрики оформления по каждому слайду (C7): по находкам не видно, стала колода
        # лучше или просто не дошла до порога. Считаются по тем же картинкам, что уже
        # прочитаны, — это миллисекунды на слайд.
        metrics = await asyncio.to_thread(
            partial(
                slide_metrics,
                pngs,
                {slide.slide_id: slide.layout_id for slide in state["deck"].slides},
                chrome,
                **_design_tolerances(deps.run.audit),
            )
        )

    return {
        "audit": report,
        "design_metrics": metrics,
        "skipped_checks": runner.skipped_checks,
        "stage_timings_s": timings,
        "degradations": degradations,
    }
