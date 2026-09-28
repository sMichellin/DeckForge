"""FastAPI-приложение. Change (23) `service-api`.

Ничего, кроме вызова pipeline: загрузка шаблона и контента, постановка задачи в очередь,
прогресс, артефакты, выбор фиксов. Ни одного решения о содержании колоды здесь нет и быть
не должно (ARCHITECTURE.md §3).

**Файлы загружаются телом запроса, а не формой.** `multipart/form-data` в FastAPI требует
`python-multipart`, которого в зависимостях нет, а тащить зависимость ради формы,
когда загружается ровно один файл на запрос, незачем: `PUT` с телом описывает то же
самое и не требует ничего.

**Прогон не стартует сам после загрузки.** Создание, загрузка и старт разделены
намеренно: материалов может быть несколько файлов, и приложение не может угадать,
догрузит пользователь ещё один или уже нет. `POST /runs/{id}/start` — это его слово.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from deckforge.api.examples import TEMPLATE_CACHE_DIR, example_preview
from deckforge.api.queue import RESUME_JOB, RUN_JOB, ArqQueue, Queue
from deckforge.api.schemas import FindingView, FixSelection, RunCreated, RunRequest, RunStatus
from deckforge.api.store import FINAL_STATES, RunStore
from deckforge.config import available_profiles, get_settings

#: Форматы экспорта и их типы. Список закрыт: отдавать по имени расширения что угодно
#: из каталога прогона значило бы раздавать чекпойнт и загруженные материалы.
EXPORT_TYPES: dict[str, str] = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
    "html": "text/html; charset=utf-8",
}

MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def create_app(
    store: RunStore | None = None,
    queue: Queue | None = None,
    cache_root: Path | None = None,
) -> FastAPI:
    """Приложение. Хранилище и очередь передаются снаружи — тестам и inline-режиму.

    По умолчанию берётся arq: в `docker/compose.yaml` воркер поднят отдельным сервисом,
    потому что рендер превью запускает `soffice` подпроцессом и в соседний контейнер
    не дотянется.

    `cache_root` — кэш шаблонов, куда рендер кладёт превью слайдов-примеров; по умолчанию
    тот же, что у графа (`api/jobs.py`).
    """
    settings = get_settings()
    runs = store or RunStore(Path(settings.artifacts_dir) / "runs")
    cache = cache_root or Path(settings.artifacts_dir) / TEMPLATE_CACHE_DIR
    jobs_queue = queue or ArqQueue(settings.redis_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await jobs_queue.close()

    app = FastAPI(title="DeckForge", version="23", lifespan=lifespan)
    app.state.store = runs
    app.state.queue = jobs_queue
    app.include_router(_router(runs, jobs_queue, cache))
    return app


def _router(store: RunStore, queue: Queue, cache_root: Path) -> APIRouter:
    router = APIRouter()

    def known(run_id: str) -> str:
        try:
            safe = RunStore.safe_id(run_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not store.exists(safe):
            raise HTTPException(status_code=404, detail=f"прогон {safe} не найден")
        return safe

    async def read_body(request: Request) -> bytes:
        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="пустое тело запроса")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="файл больше 200 МБ")
        return data

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/profiles")
    async def profiles() -> dict[str, list[str]]:
        """Какие профили прогона есть. Интерфейсу — чтобы не знать их наперечёт."""
        return {"profiles": available_profiles()}

    @router.post("/runs", status_code=201)
    async def create_run(request: RunRequest) -> RunCreated:
        # Опечатку в имени профиля ловим здесь, а не через 150 секунд прогона:
        # `load_run_config` несуществующий файл молча пропускает, и человек получил бы
        # базовый конфиг вместо запрошенного, не узнав об этом.
        known_profiles = available_profiles()
        if request.profile is not None and request.profile not in known_profiles:
            raise HTTPException(
                status_code=400,
                detail=f"профиль {request.profile} не найден: есть {', '.join(known_profiles)}",
            )
        run_id = store.create(request=request.model_dump(mode="json"))
        return RunCreated(run_id=run_id)

    @router.put("/runs/{run_id}/template", status_code=204)
    async def upload_template(
        run_id: str, request: Request, filename: str = "template.pptx"
    ) -> Response:
        store.save_template(known(run_id), filename, await read_body(request))
        return Response(status_code=204)

    @router.put("/runs/{run_id}/content/{name}", status_code=204)
    async def upload_content(run_id: str, name: str, request: Request) -> Response:
        store.save_content(known(run_id), name, await read_body(request))
        return Response(status_code=204)

    @router.post("/runs/{run_id}/start", status_code=202)
    async def start_run(run_id: str) -> RunCreated:
        safe = known(run_id)
        paths = store.paths(safe)
        if not paths.template.exists():
            raise HTTPException(status_code=409, detail="шаблон не загружен")
        if not any(paths.content.iterdir()):
            raise HTTPException(status_code=409, detail="не загружено ни одного материала")
        store.write_status(safe, state="queued", stage=None)
        await queue.submit(RUN_JOB, safe)
        return RunCreated(run_id=safe, state="queued")

    @router.get("/runs/{run_id}")
    async def run_status(run_id: str) -> RunStatus:
        return RunStatus.of(store.status(known(run_id)))

    @router.get("/runs/{run_id}/report")
    async def run_report(run_id: str) -> JSONResponse:
        report = store.report(known(run_id))
        if report is None:
            raise HTTPException(status_code=409, detail="отчёта ещё нет: прогон не дошёл до конца")
        return JSONResponse(report)

    @router.get("/runs/{run_id}/findings")
    async def run_findings(run_id: str) -> list[FindingView]:
        """Находки, на которые граф ждёт ответа.

        Пустой список — законный ответ, и он не значит «нарушений нет»: он значит,
        что выбор сейчас не нужен. Что именно нашёл аудит, лежит в `run.json`.
        """
        status = store.status(known(run_id))
        return [FindingView.of(item) for item in status.get("findings") or []]

    @router.post("/runs/{run_id}/fixes", status_code=202)
    async def choose_fixes(run_id: str, selection: FixSelection) -> RunCreated:
        safe = known(run_id)
        status = store.status(safe)
        if status.get("state") != "waiting_choice":
            raise HTTPException(
                status_code=409,
                detail=f"прогон не ждёт выбора (состояние {status.get('state')!r})",
            )
        offered = {str(item.get("finding_id")) for item in status.get("findings") or []}
        unknown = sorted(set(selection.finding_ids) - offered)
        if unknown:
            # Молча отбросить чужой id значило бы сказать «починили», не починив.
            raise HTTPException(
                status_code=400, detail=f"находки не предлагались к починке: {', '.join(unknown)}"
            )
        store.write_status(safe, state="queued", stage="hitl")
        await queue.submit(RESUME_JOB, safe, selection.finding_ids)
        return RunCreated(run_id=safe, state="queued")

    @router.get("/runs/{run_id}/previews/{slide_id}")
    async def preview(run_id: str, slide_id: str) -> FileResponse:
        path = store.preview_of(known(run_id), slide_id)
        if path is None:
            raise HTTPException(status_code=404, detail="превью этого слайда нет")
        return FileResponse(path, media_type="image/png")

    @router.get("/runs/{run_id}/examples/{recipe_id}")
    async def example(run_id: str, recipe_id: str) -> FileResponse:
        """Превью слайда-примера шаблона прогона — для листа колоды (план Б, шаг 6).

        Из кэша, который наполняет рендер: сервис сам не рендерит. Нет превью — 404,
        и лист показывает слайд без примера, а не падает.
        """
        path = example_preview(store.paths(known(run_id)).template, recipe_id, cache_root)
        if path is None:
            raise HTTPException(status_code=404, detail=f"превью примера {recipe_id} нет")
        return FileResponse(path, media_type="image/png")

    @router.get("/runs/{run_id}/exports/{fmt}")
    async def export(run_id: str, fmt: str) -> FileResponse:
        safe = known(run_id)
        media = EXPORT_TYPES.get(fmt.lower())
        if media is None:
            raise HTTPException(status_code=404, detail=f"формат {fmt!r} не экспортируется")
        report = store.report(safe) or {}
        raw = (report.get("exports") or {}).get(fmt.lower())
        if not raw or not Path(raw).exists():
            state = store.status(safe).get("state")
            detail = (
                f"экспорта {fmt} нет"
                if state in FINAL_STATES
                else f"экспорта {fmt} ещё нет: прогон не закончен"
            )
            raise HTTPException(status_code=409, detail=detail)
        return FileResponse(Path(raw), media_type=media, filename=f"{safe}.{fmt.lower()}")

    return router


def _app_factory() -> Any:  # pragma: no cover — точка входа uvicorn из compose
    return create_app()
