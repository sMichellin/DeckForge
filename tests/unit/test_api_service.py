"""Транспорт: маршруты, хранилище прогона, очередь. Change (23) `service-api`.

Ни Redis, ни живой генерации здесь нет и быть не должно. Приложение обязано только
принять файлы, положить задачу в очередь и честно рассказать, где прогон сейчас, —
всё остальное делает `pipeline`, и у него свои тесты.

Очередь подменяется записной книжкой: так видно, **что** приложение поставило в очередь,
а не только то, что оно не упало.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from deckforge.api.app import create_app
from deckforge.api.jobs import _finish, _with_relative_boxes
from deckforge.api.queue import RESUME_JOB, RUN_JOB, InlineQueue
from deckforge.api.store import RunStore, progress_of
from deckforge.api.worker import WorkerSettings
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline import RunResult

PPTX = b"PK\x03\x04" + b"0" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class SpyQueue:
    """Очередь, которая ничего не исполняет, но помнит, о чём её просили."""

    def __init__(self) -> None:
        self.submitted: list[tuple[str, str, tuple[Any, ...]]] = []
        self.closed = False

    async def submit(self, job: str, run_id: str, *args: Any) -> None:
        self.submitted.append((job, run_id, args))

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "runs")


@pytest.fixture
def queue() -> SpyQueue:
    return SpyQueue()


@pytest.fixture
def client(store: RunStore, queue: SpyQueue) -> TestClient:
    return TestClient(create_app(store=store, queue=queue))


def start_run(client: TestClient, **fields: Any) -> str:
    created = client.post("/runs", json={"variant": "A", **fields})
    assert created.status_code == 201
    run_id = created.json()["run_id"]
    template = client.put(f"/runs/{run_id}/template?filename=deck.pptx", content=PPTX)
    assert template.status_code == 204
    assert client.put(f"/runs/{run_id}/content/brief.md", content=b"# brief").status_code == 204
    return str(run_id)


# --- путь пользователя -------------------------------------------------------


def test_uploaded_run_reaches_the_queue(client: TestClient, queue: SpyQueue) -> None:
    run_id = start_run(client)

    assert client.post(f"/runs/{run_id}/start").status_code == 202

    assert queue.submitted == [(RUN_JOB, run_id, ())]


def test_run_without_a_template_does_not_start(client: TestClient, queue: SpyQueue) -> None:
    """Иначе задача уедет в очередь и упадёт уже там, где пользователь её не видит."""
    run_id = client.post("/runs", json={}).json()["run_id"]
    client.put(f"/runs/{run_id}/content/brief.md", content=b"# brief")

    answer = client.post(f"/runs/{run_id}/start")

    assert answer.status_code == 409
    assert "шаблон" in answer.json()["detail"]
    assert queue.submitted == []


def test_run_without_content_does_not_start(client: TestClient, queue: SpyQueue) -> None:
    run_id = client.post("/runs", json={}).json()["run_id"]
    client.put(f"/runs/{run_id}/template", content=PPTX)

    answer = client.post(f"/runs/{run_id}/start")

    assert answer.status_code == 409
    assert queue.submitted == []


def test_empty_upload_is_refused(client: TestClient) -> None:
    run_id = client.post("/runs", json={}).json()["run_id"]

    assert client.put(f"/runs/{run_id}/template", content=b"").status_code == 400


def test_unknown_run_is_not_found(client: TestClient) -> None:
    assert client.get("/runs/abcdef123456").status_code == 404


def test_run_id_from_the_url_cannot_escape_the_store(client: TestClient) -> None:
    """`run_id` уходит в путь, поэтому он проверяется, а не чистится от «..»."""
    assert client.get("/runs/..%2F..%2Fetc").status_code in (400, 404)
    assert client.get("/runs/nothex!!").status_code == 400


# --- статус ------------------------------------------------------------------


def test_fresh_run_is_queued(client: TestClient) -> None:
    run_id = start_run(client)

    status = client.get(f"/runs/{run_id}").json()

    assert status["state"] == "queued"
    assert status["progress"] == 0.0
    assert status["findings"] == []


def test_progress_counts_finished_stages_only() -> None:
    """Ни одной догадки о том, сколько осталось внутри стадии: полоска не врёт."""
    assert progress_of(None, "queued") == 0.0
    assert progress_of("plan", "running") == 0.375
    assert progress_of("export", "running") == 1.0
    assert progress_of(None, "done") == 1.0


def test_failed_run_says_why(client: TestClient, store: RunStore) -> None:
    run_id = start_run(client)
    store.write_status(run_id, state="failed", stage="plan", error="модель не ответила")

    status = client.get(f"/runs/{run_id}").json()

    assert status["state"] == "failed"
    assert status["error"] == "модель не ответила"


# --- выбор фиксов ------------------------------------------------------------


def waiting(store: RunStore, run_id: str) -> dict[str, Any]:
    finding = {
        "finding_id": "f1",
        "check_id": "layout.text_overflow",
        "severity": "error",
        "message": "текст не помещается",
        "slide_id": "s01",
        "block_id": "b1",
        "bbox_emu": {"x": 1, "y": 2, "cx": 3, "cy": 4},
        "auto_fix": "shrink_font",
    }
    return store.write_status(run_id, state="waiting_choice", stage="hitl", findings=[finding])


def test_findings_carry_the_box_to_highlight(client: TestClient, store: RunStore) -> None:
    """Подсветка находки на превью — требование ТЗ, и `bbox_emu` для неё уже есть."""
    run_id = start_run(client)
    waiting(store, run_id)

    findings = client.get(f"/runs/{run_id}/findings").json()

    assert findings[0]["bbox_emu"] == {"x": 1, "y": 2, "cx": 3, "cy": 4}
    assert findings[0]["auto_fix"] == "shrink_font"


def test_chosen_fixes_go_back_to_the_graph(
    client: TestClient, store: RunStore, queue: SpyQueue
) -> None:
    run_id = start_run(client)
    waiting(store, run_id)

    answer = client.post(f"/runs/{run_id}/fixes", json={"finding_ids": ["f1"]})

    assert answer.status_code == 202
    assert queue.submitted == [(RESUME_JOB, run_id, (["f1"],))]


def test_choosing_nothing_is_a_valid_answer(
    client: TestClient, store: RunStore, queue: SpyQueue
) -> None:
    """«Ничего не чинить» — решение пользователя, а не отсутствие решения."""
    run_id = start_run(client)
    waiting(store, run_id)

    assert client.post(f"/runs/{run_id}/fixes", json={"finding_ids": []}).status_code == 202
    assert queue.submitted == [(RESUME_JOB, run_id, ([],))]


def test_unknown_finding_is_refused_not_dropped(
    client: TestClient, store: RunStore, queue: SpyQueue
) -> None:
    """Молча отбросить чужой id значило бы сказать «починили», не починив."""
    run_id = start_run(client)
    waiting(store, run_id)

    answer = client.post(f"/runs/{run_id}/fixes", json={"finding_ids": ["f1", "f404"]})

    assert answer.status_code == 400
    assert "f404" in answer.json()["detail"]
    assert queue.submitted == []


def test_fixes_are_refused_while_the_run_is_going(
    client: TestClient, store: RunStore, queue: SpyQueue
) -> None:
    run_id = start_run(client)
    store.write_status(run_id, state="running", stage="compose")

    answer = client.post(f"/runs/{run_id}/fixes", json={"finding_ids": []})

    assert answer.status_code == 409
    assert queue.submitted == []


# --- артефакты ---------------------------------------------------------------


def rendered(store: RunStore, run_id: str, slide_id: str = "s01") -> None:
    """Превью так, как их кладёт рендер: страницами, а не именами слайдов."""
    previews = store.paths(run_id).previews
    previews.mkdir(parents=True, exist_ok=True)
    page = previews / "deck-1.png"
    page.write_bytes(PNG)
    store.save_previews(run_id, {slide_id: page})


def test_preview_is_served_by_slide_id(client: TestClient, store: RunStore) -> None:
    """Рендер именует страницы `deck-1.png`, а находки знают только `slide_id`."""
    run_id = start_run(client)
    rendered(store, run_id)

    answer = client.get(f"/runs/{run_id}/previews/s01")

    assert answer.status_code == 200
    assert answer.headers["content-type"] == "image/png"
    assert answer.content == PNG


def test_preview_without_an_index_is_not_guessed(client: TestClient, store: RunStore) -> None:
    """Собрать имя из `slide_id` значило бы угадывать: у рендера имена другие."""
    run_id = start_run(client)
    previews = store.paths(run_id).previews
    previews.mkdir(parents=True, exist_ok=True)
    (previews / "deck-1.png").write_bytes(PNG)

    assert client.get(f"/runs/{run_id}/previews/s01").status_code == 404


def test_preview_index_cannot_point_outside_the_run(store: RunStore) -> None:
    """Указатель пишем мы, но на другом конце путь файловой системы — проверяем."""
    run_id = store.create(request={"variant": "A"})
    store.paths(run_id).previews.mkdir(parents=True, exist_ok=True)
    store.paths(run_id).previews_index.write_text(
        json.dumps({"s01": "../../request.json"}), encoding="utf-8"
    )

    assert store.preview_of(run_id, "s01") is None


def test_preview_name_is_matched_not_built(client: TestClient, store: RunStore) -> None:
    """`slide_id` придумывает модель и приходит он из URL — в путь он не подставляется."""
    run_id = start_run(client)
    rendered(store, run_id)

    assert client.get(f"/runs/{run_id}/previews/..%2F..%2Frequest").status_code == 404


def test_export_is_served_from_the_report(client: TestClient, store: RunStore) -> None:
    run_id = start_run(client)
    deck = store.paths(run_id).out / "deck.pptx"
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_bytes(PPTX)
    store.paths(run_id).report_file.write_text(
        json.dumps({"exports": {"pptx": str(deck)}}), encoding="utf-8"
    )

    answer = client.get(f"/runs/{run_id}/exports/pptx")

    assert answer.status_code == 200
    assert answer.content == PPTX


def test_export_that_was_never_made_is_not_a_404(client: TestClient, store: RunStore) -> None:
    """404 значил бы «нет такого адреса». Экспорта нет потому, что прогон не дошёл."""
    run_id = start_run(client)

    answer = client.get(f"/runs/{run_id}/exports/pdf")

    assert answer.status_code == 409
    assert "не закончен" in answer.json()["detail"]


def test_only_declared_formats_are_served(client: TestClient) -> None:
    """Иначе по имени расширения раздавался бы чекпойнт и загруженные материалы."""
    run_id = start_run(client)

    assert client.get(f"/runs/{run_id}/exports/sqlite").status_code == 404


# --- очередь и воркер --------------------------------------------------------


def test_worker_job_names_match_the_queue() -> None:
    """Очередь кладёт в Redis имя, а не ссылку: разошлись имена — задачу никто не возьмёт."""
    assert {fn.__name__ for fn in WorkerSettings.functions} == {RUN_JOB, RESUME_JOB}


async def test_inline_queue_keeps_a_reference_to_its_task(store: RunStore) -> None:
    """Без ссылки сборщик мусора вправе забрать задачу, и прогон оборвётся молча."""
    inline = InlineQueue(store=store)
    run_id = store.create(request={"variant": "A"})

    await inline.submit(RUN_JOB, run_id)

    assert len(inline.tasks) == 1
    await inline.close()


def test_queue_is_closed_with_the_app(store: RunStore, queue: SpyQueue) -> None:
    with TestClient(create_app(store=store, queue=queue)):
        pass

    assert queue.closed is True


# --- деградация и ошибка — разные поля ---------------------------------------


def finished_result(out_dir: Path, **state: Any) -> RunResult:
    """Прогон, дошедший до конца. Всё, чего нет в `state`, отчёт считает пустым."""
    return RunResult(variant="A", run_id="r1", out_dir=out_dir, state=state)  # type: ignore[arg-type]


def test_degradation_does_not_land_in_the_error_of_a_successful_run(
    store: RunStore, tmp_path: Path
) -> None:
    """Дефект 19.09: прогон `done` приходил в интерфейс с текстом в поле ошибки.

    `api/jobs.py` складывал `errors` и `degradations` в одно поле, и выключенный
    по бюджету смысловой аудит выглядел как сбой удачного прогона.
    """
    run_id = store.create(request={"variant": "A"})
    result = finished_result(
        tmp_path,
        degradations=["audit: смысловой аудит выключен — остатка бюджета не хватает (§15)"],
    )

    status = _finish(run_id, store, result, elapsed_s=1.0)

    assert status["state"] == "done"
    assert status["error"] is None
    assert status["degradations"] == [
        "audit: смысловой аудит выключен — остатка бюджета не хватает (§15)"
    ]


def test_real_errors_still_reach_the_error_field(store: RunStore, tmp_path: Path) -> None:
    """Норма к той же правке: сбой прячется за зелёным статусом не больше прежнего."""
    run_id = store.create(request={"variant": "A"})
    result = finished_result(tmp_path, errors=["export: pdf не собрался"], degradations=["x"])

    status = _finish(run_id, store, result, elapsed_s=1.0)

    assert status["error"] == "export: pdf не собрался"
    assert status["degradations"] == ["x"]


def test_status_carries_degradations_to_the_client(client: TestClient, store: RunStore) -> None:
    run_id = start_run(client)
    store.write_status(run_id, state="done", stage="export", degradations=["превью не сняты"])

    assert client.get(f"/runs/{run_id}").json()["degradations"] == ["превью не сняты"]


# --- рамка находки для подсветки ---------------------------------------------


def interrupted_result(state: dict[str, Any]) -> RunResult:
    return RunResult(variant="A", run_id="r1", out_dir=Path("."), state=state)  # type: ignore[arg-type]


def test_finding_gets_the_share_of_the_slide(manifest: TemplateManifest) -> None:
    """Интерфейс рисует подсветку поверх картинки своего размера: EMU ему не годятся."""
    size = manifest.slide_size
    box = {"x": size.cx_emu // 4, "y": 0, "cx": size.cx_emu // 2, "cy": size.cy_emu}
    result = interrupted_result(
        {
            "manifest": manifest,
            "__interrupt__": [
                SimpleNamespace(value={"findings": [{"finding_id": "f1", "bbox_emu": box}]})
            ],
        }
    )

    assert _with_relative_boxes(result)[0]["bbox_rel"] == {
        "x": 0.25,
        "y": 0.0,
        "cx": 0.5,
        "cy": 1.0,
    }


def test_finding_without_a_box_is_left_alone(manifest: TemplateManifest) -> None:
    """Смысловая находка указывает на слайд целиком — подсвечивать в нём нечего."""
    result = interrupted_result(
        {
            "manifest": manifest,
            "__interrupt__": [SimpleNamespace(value={"findings": [{"finding_id": "f1"}]})],
        }
    )

    assert "bbox_rel" not in _with_relative_boxes(result)[0]


def test_missing_manifest_does_not_break_the_choice() -> None:
    """Прогон мог остановиться и без манифеста: выбор фиксов важнее подсветки."""
    result = interrupted_result(
        {"__interrupt__": [SimpleNamespace(value={"findings": [{"finding_id": "f1"}]})]}
    )

    assert [f["finding_id"] for f in _with_relative_boxes(result)] == ["f1"]
