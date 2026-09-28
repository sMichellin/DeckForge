"""Долгая работа прогона. Change (23) `service-api`.

Здесь нет ни одного решения о содержании колоды — только вызов `pipeline` и запись
того, что он вернул (ARCHITECTURE.md §3, строка «api / cli / ui»). Файл отделён
от `worker.py` затем, чтобы задачу можно было прогнать без arq и без Redis: в тестах
и в `deckforge serve --inline` она зовётся напрямую.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any

from deckforge.api.examples import TEMPLATE_CACHE_DIR
from deckforge.api.store import RunStore
from deckforge.config import get_settings, load_run_config
from deckforge.domain.content import Brief
from deckforge.pipeline import (
    RunResult,
    build_deps,
    collect_content_paths,
    generate_variant,
    resume_variant,
    variants_for,
)

#: Как часто воркер переписывает статус, пока идёт прогон. Полсекунды — чтобы полоска
#: двигалась заметно, но статус не переписывался чаще, чем человек успевает смотреть.
POLL_INTERVAL_S = 0.5


async def run_job(run_id: str, store: RunStore) -> dict[str, Any]:
    """Сгенерировать вариант. Остановка на выборе фиксов — законный исход, а не ошибка."""
    return await _work(run_id, store, selected=None)


async def resume_job(run_id: str, store: RunStore, selected: list[str]) -> dict[str, Any]:
    """Продолжить прогон после выбора человека."""
    return await _work(run_id, store, selected=selected)


async def _work(run_id: str, store: RunStore, *, selected: list[str] | None) -> dict[str, Any]:
    paths = store.paths(run_id)
    request = store.request(run_id)
    started = time.perf_counter()

    try:
        deps, profile = _prepare(request, paths)
    # Причина уезжает пользователю в статус, а не в лог: прогон запускал человек.
    except Exception as error:
        return store.write_status(run_id, state="failed", stage=None, error=str(error))

    store.write_status(run_id, state="running", stage=None)
    reporter = asyncio.create_task(_report_progress(run_id, store, deps, started))
    try:
        if selected is None:
            result = await generate_variant(
                paths.template,
                collect_content_paths(paths.content),
                profile,
                deps,
                seed=int(request.get("seed", 1337)),
                checkpoint_path=paths.checkpoint,
                run_id=run_id,
            )
        else:
            result = await resume_variant(
                profile,
                deps,
                run_id=run_id,
                selected=selected,
                checkpoint_path=paths.checkpoint,
            )
    # Прогон упал — статус обязан это сказать, а не остаться в «running» навсегда.
    except Exception as error:
        return store.write_status(
            run_id,
            state="failed",
            stage=_last_stage(deps),
            elapsed_s=time.perf_counter() - started,
            error=f"{type(error).__name__}: {error}",
        )
    finally:
        reporter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reporter

    return _finish(run_id, store, result, elapsed_s=time.perf_counter() - started)


def _slides(raw: Any) -> int | None:
    """Число слайдов из запроса: `None` — автоматический режим."""
    return None if raw is None else int(raw)


def _prepare(request: dict[str, Any], paths: Any) -> tuple[Any, Any]:
    """Зависимости прогона по запросу. Живые клиенты собирает `pipeline.build_deps`.

    Профилей здесь два, и это разные вещи. `run_profile` — набор настроек прогона
    (`configs/profiles/*.yaml`): им включается смысловой аудит, им же задаются форматы
    и модели. `profile` ниже — вариант вёрстки A/B/C, который уедет в граф.
    """
    run_profile = request.get("profile")
    run = load_run_config(profile=str(run_profile) if run_profile else None)
    brief = Brief(
        purpose=str(request.get("purpose", "report")),
        audience=str(request.get("audience", "правление")),
        # `null` — число подбирает план (Т1); поле не передано — прежние 12.
        target_slides=_slides(request.get("target_slides", 12)),
        language=str(request.get("language", "ru")),
    )
    profile = variants_for([str(request.get("variant", "A"))])[0]
    deps = build_deps(
        brief,
        run,
        paths.out,
        cache_dir=Path(get_settings().artifacts_dir) / TEMPLATE_CACHE_DIR,
        asset_dir=paths.out / "assets",
        interactive=bool(request.get("interactive", True)),
        profile=get_settings().profile,
    )
    return deps, profile


def _finish(
    run_id: str, store: RunStore, result: RunResult, *, elapsed_s: float
) -> dict[str, Any]:
    """Итог прогона в статус. Отчёт пишется всегда — даже когда граф остановлен."""
    result.write_report()
    # Указатель на превью нужен раньше отчёта: без него слайд и картинку не связать,
    # а интерфейс просит превью именно по `slide_id`.
    store.save_previews(run_id, dict(result.state.get("previews") or {}))
    if result.interrupted:
        return store.write_status(
            run_id,
            state="waiting_choice",
            stage="hitl",
            elapsed_s=elapsed_s,
            findings=_with_relative_boxes(result),
        )
    report = result.report()
    # Прогон дошёл до конца, но мог дойти с потерями: они уже в `run.json`, и прятать
    # их за зелёным статусом нельзя — пользователь должен открыть отчёт.
    #
    # Потери бывают двух родов, и складывать их в одно поле было неправильно. Деградация
    # (§15) — это выбор пайплайна: смысловой аудит выключен, превью не сняты, колода
    # при этом собрана. Ошибка — что-то не отработало. Пока и то и другое ехало в `error`,
    # удачный прогон приходил в интерфейс с красным текстом и выглядел как сбой.
    return store.write_status(
        run_id,
        state="done",
        stage="export",
        elapsed_s=elapsed_s,
        error="; ".join(report["errors"]) or None,
        degradations=list(report["degradations"]),
    )


def _with_relative_boxes(result: RunResult) -> list[dict[str, Any]]:
    """Находки, к рамке которых добавлена доля слайда.

    Интерфейс подсвечивает находку поверх превью, а превью — картинка, размер которой
    он выбирает сам. Пересчёт EMU в пиксели требует размера слайда; знает его манифест,
    а манифест до интерфейса не доезжает и доезжать не должен. Доля — наименьшее,
    чего достаточно для подсветки, и она не устаревает при смене масштаба.
    """
    size = getattr(result.state.get("manifest"), "slide_size", None)
    findings = result.pending_findings()
    if size is None or not size.cx_emu or not size.cy_emu:
        return findings

    enriched: list[dict[str, Any]] = []
    for raw in findings:
        box = raw.get("bbox_emu")
        if not box:
            enriched.append(raw)
            continue
        enriched.append(
            {
                **raw,
                "bbox_rel": {
                    "x": box["x"] / size.cx_emu,
                    "y": box["y"] / size.cy_emu,
                    "cx": box["cx"] / size.cx_emu,
                    "cy": box["cy"] / size.cy_emu,
                },
            }
        )
    return enriched


async def _report_progress(run_id: str, store: RunStore, deps: Any, started: float) -> None:
    """Пишет статус, пока граф идёт.

    Стадия берётся из часов бюджета: `timed()` кладёт туда каждую завершённую стадию,
    и это единственный источник, который уже есть. Своего канала прогресса заводить
    не стали — он потребовал бы обратного вызова в `Deps`, то есть правки графа
    ради полоски.
    """
    while True:
        await asyncio.sleep(POLL_INTERVAL_S)
        store.write_status(
            run_id,
            state="running",
            stage=_last_stage(deps),
            elapsed_s=time.perf_counter() - started,
        )


def _last_stage(deps: Any) -> str | None:
    timings = getattr(getattr(deps, "budget", None), "timings", None) or {}
    return next(reversed(list(timings)), None)
