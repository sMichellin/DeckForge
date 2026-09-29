"""Варианты вёрстки называются словами. Change `the-variants-are-named` (план Б, круг 3).

Человек в интерфейсе выбирал «A», «B» или «C» и не знал, что за буквой. Названия живут
в `configs/variants.yaml`; сервис их отдаёт, интерфейс показывает, а в прогон уходит буква.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from frontend.client import DeckForgeClient

from deckforge.api.app import create_app
from deckforge.api.store import RunStore
from deckforge.registry.variants import load_variant_profiles

APP = Path(__file__).resolve().parents[2] / "frontend" / "app.py"


class _Queue:
    async def submit(self, job: str, run_id: str, *args: Any) -> None:
        return None

    async def close(self) -> None:
        return None


def test_the_service_names_every_variant_from_the_config(tmp_path: Path) -> None:
    """Норма: `GET /variants` отдаёт каждую букву с названием и обоснованием из конфига."""
    client = TestClient(create_app(store=RunStore(tmp_path / "runs"), queue=_Queue()))

    answer = client.get("/variants")

    assert answer.status_code == 200
    rows = {row["variant_id"]: row for row in answer.json()["variants"]}
    profiles = load_variant_profiles()
    assert set(rows) == set(profiles)
    for vid, profile in profiles.items():
        assert rows[vid]["name"] == profile.name
        assert rows[vid]["name"] != vid
        assert rows[vid]["rationale"]


def _service(handler: Any) -> DeckForgeClient:
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://service")
    return DeckForgeClient(base_url="http://service", _http=http)


def test_the_client_maps_letters_to_names() -> None:
    """Норма: клиент отдаёт интерфейсу «буква → название»."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/variants"
        rows = [{"variant_id": "A", "name": "Плотный"}, {"variant_id": "B", "name": "Нарратив"}]
        return httpx.Response(200, json={"variants": rows})

    assert _service(handler).variants() == {"A": "Плотный", "B": "Нарратив"}


def test_a_dead_service_leaves_the_letters() -> None:
    """Нарушитель: сервис недоступен — пустой словарь, а не ошибка панели."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сервиса")

    assert _service(handler).variants() == {}


def test_the_page_still_offers_variants_without_the_service() -> None:
    """Нарушитель: без сервиса вариант всё равно выбирается — буквой, страница не падает."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(APP), default_timeout=30)
    app.run()

    assert not app.exception
    radio = next(item for item in app.radio if item.label == "Вариант вёрстки")
    # Последний пункт — «все сразу» (change `three-variants-at-once`), до него — буквы.
    assert list(radio.options)[:3] == ["A", "B", "C"]
