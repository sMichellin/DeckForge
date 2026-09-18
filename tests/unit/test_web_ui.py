"""Интерфейс: разговор с сервисом и подсветка находок. Change (23) `web-ui`.

Живого сервиса здесь нет — вместо него подставной транспорт httpx. Проверяется то,
что можно проверить без глаз: какие адреса дёргает клиент, как он читает отказы
и где именно оказывается рамка на картинке. Саму разметку проверяет только человек,
поэтому в `app.py` логики нет.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import httpx
import pytest
from frontend.client import DeckForgeClient, ServiceError
from frontend.highlight import SEVERITY_COLORS, box_in_pixels, by_slide, color_for, draw_findings
from PIL import Image

WIDTH, HEIGHT = 400, 300

#: `AppTest` считает путь от файла, который его зовёт, — значит, путь абсолютный.
APP = Path(__file__).resolve().parents[2] / "frontend" / "app.py"


def png(width: int = WIDTH, height: int = HEIGHT) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def service(handler: Any) -> DeckForgeClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://service")
    return DeckForgeClient(base_url="http://service", _http=http)


# --- клиент ------------------------------------------------------------------


def test_run_is_created_uploaded_and_started() -> None:
    """Порядок важен: старт последним, иначе прогон уедет без половины материалов."""
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/runs":
            return httpx.Response(201, json={"run_id": "abc123"})
        return httpx.Response(204)

    api = service(handler)
    run_id = api.create_run(variant="A")
    api.upload_template(run_id, "deck.pptx", b"PK")
    api.upload_content(run_id, "brief.md", b"# brief")
    api.start(run_id)

    assert seen == [
        ("POST", "/runs"),
        ("PUT", "/runs/abc123/template"),
        ("PUT", "/runs/abc123/content/brief.md"),
        ("POST", "/runs/abc123/start"),
    ]


def test_template_name_travels_as_a_parameter() -> None:
    """Имя нужно сервису только ради расширения — в путь оно не идёт."""
    captured: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url)
        return httpx.Response(204)

    service(handler).upload_template("abc123", "Шаблон 2024.potx", b"PK")

    assert captured[0].params["filename"] == "Шаблон 2024.potx"
    assert captured[0].path == "/runs/abc123/template"


def test_refusal_carries_the_reason_from_the_service() -> None:
    """Пересказывать отказ своими словами значит терять причину."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "шаблон не загружен"})

    with pytest.raises(ServiceError) as error:
        service(handler).start("abc123")

    assert error.value.status == 409
    assert error.value.detail == "шаблон не загружен"


def test_refusal_without_json_does_not_break_the_client() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    with pytest.raises(ServiceError) as error:
        service(handler).status("abc123")

    assert "Bad Gateway" in error.value.detail


def test_report_that_is_not_ready_is_not_an_error() -> None:
    """409 здесь значит «рано», и краснеть интерфейсу незачем."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "отчёта ещё нет"})

    assert service(handler).report("abc123") is None


def test_missing_preview_is_not_an_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "превью этого слайда нет"})

    assert service(handler).preview("abc123", "s01") is None


def test_export_that_is_not_ready_is_not_an_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "прогон не закончен"})

    assert service(handler).export("abc123", "pdf") is None


def test_empty_choice_is_sent_as_a_choice() -> None:
    """«Ничего не чинить» — решение пользователя, и оно должно доехать до сервиса."""
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(202, json={"run_id": "abc123"})

    service(handler).choose_fixes("abc123", [])

    assert b'"finding_ids":[]' in bodies[0].replace(b" ", b"")


# --- подсветка ---------------------------------------------------------------


def test_share_of_the_slide_becomes_pixels() -> None:
    assert box_in_pixels({"x": 0.25, "y": 0.5, "cx": 0.5, "cy": 0.25}, WIDTH, HEIGHT) == (
        100,
        150,
        300,
        225,
    )


def test_box_outside_the_slide_is_trimmed_not_dropped() -> None:
    """Находка может выходить за край — ровно это ловит `layout.out_of_bounds`."""
    box = {"x": 0.8, "y": 0.0, "cx": 0.5, "cy": 1.0}
    left, top, right, bottom = box_in_pixels(box, WIDTH, HEIGHT)

    assert (left, top) == (320, 0)
    assert right == WIDTH and bottom == HEIGHT


def test_degenerate_box_still_has_a_side() -> None:
    """Нулевая рамка не рисуется вовсе, а находка при этом есть."""
    box = {"x": 0.5, "y": 0.5, "cx": 0.0, "cy": 0.0}
    left, top, right, bottom = box_in_pixels(box, WIDTH, HEIGHT)

    assert right > left and bottom > top


def test_severity_picks_the_colour() -> None:
    assert color_for("error") == SEVERITY_COLORS["error"]
    assert color_for("ERROR") == SEVERITY_COLORS["error"]
    assert color_for("не знаю такого") not in SEVERITY_COLORS.values()


def test_finding_is_drawn_where_it_points() -> None:
    finding = {"severity": "error", "bbox_rel": {"x": 0.25, "y": 0.25, "cx": 0.5, "cy": 0.5}}

    image = Image.open(io.BytesIO(draw_findings(png(), [finding])))

    assert image.size == (WIDTH, HEIGHT)
    assert image.getpixel((100, 75)) == SEVERITY_COLORS["error"]
    # Середина рамки осталась нетронутой: обводим, а не закрашиваем.
    assert image.getpixel((WIDTH // 2, HEIGHT // 2)) == (255, 255, 255)


def test_finding_without_a_box_draws_nothing() -> None:
    """Смысловая находка про слайд целиком: обвести весь слайд значит обвинить всё."""
    untouched = draw_findings(png(), [])
    semantic = draw_findings(png(), [{"severity": "warning", "slide_id": "s01"}])

    assert Image.open(io.BytesIO(semantic)).tobytes() == Image.open(io.BytesIO(untouched)).tobytes()


def test_findings_are_grouped_by_slide_in_order() -> None:
    grouped = by_slide(
        [
            {"finding_id": "f1", "slide_id": "s02"},
            {"finding_id": "f2", "slide_id": "s01"},
            {"finding_id": "f3", "slide_id": "s02"},
            {"finding_id": "f4"},
        ]
    )

    assert list(grouped) == ["s02", "s01", ""]
    assert [f["finding_id"] for f in grouped["s02"]] == ["f1", "f3"]


# --- разметка: только то, что видно без глаз ---------------------------------


def test_page_renders_and_offers_to_upload() -> None:
    """Смоук: страница поднимается без исключений и просит файлы, а не падает молча."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(APP), default_timeout=30)
    app.run()

    assert not app.exception
    assert [title.value for title in app.title] == ["DeckForge"]


def test_nothing_uploaded_means_nothing_to_send() -> None:
    """Кнопка сбора не должна отправлять прогон без шаблона: сервис его всё равно вернёт."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(APP), default_timeout=30)
    app.run()

    collect = [button for button in app.button if button.label.startswith("Собрать")]
    assert collect and collect[0].disabled
