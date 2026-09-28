"""Интерфейс ждёт занятый сервис, но не ждёт мёртвый.
Change `the-interface-waits-out-a-busy-run` (RG57а).

На стенде интерфейс падал `httpx.ReadTimeout` на профиле `final`: таймаут был один
на все запросы и равен 30 с, а прогон живёт в цикле событий API и замораживает его
на минуты. Прогон при этом продолжался — человек видел трассу вместо статуса.

Живого медленного сервера здесь нет: подставной транспорт таймаутов не соблюдает,
поэтому проверяется то, что клиент кладёт в запрос.
"""

from __future__ import annotations

import httpx
import pytest
from frontend.client import (
    CONNECT_TIMEOUT_S,
    LOOKUP_TIMEOUT_S,
    TIMEOUT_ENV,
    TIMEOUT_S,
    DeckForgeClient,
)

#: Прежний общий таймаут: с ним и падало.
WAS_S = 30.0


def timeouts(handler: object) -> list[dict[str, float | None]]:
    """Таймауты, с которыми ушли запросы клиента."""
    seen: list[dict[str, float | None]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.extensions.get("timeout", {})))
        return httpx.Response(200, json={"profiles": ["dev"], "state": "running"})

    client = DeckForgeClient(base_url="http://service")
    client._http = httpx.Client(
        transport=httpx.MockTransport(transport),
        base_url="http://service",
        timeout=httpx.Timeout(client.timeout_s, connect=CONNECT_TIMEOUT_S),
    )
    handler(client)  # type: ignore[operator]
    return seen


def test_reading_waits_longer_than_it_used_to() -> None:
    """Терпение к занятому серверу: чтение дольше прежних 30 с, соединение — короткое."""
    assert TIMEOUT_S > WAS_S

    seen = timeouts(lambda client: client.status("abc123"))

    assert seen[0]["read"] == TIMEOUT_S
    assert seen[0]["connect"] == CONNECT_TIMEOUT_S


def test_the_long_timeout_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Число стенда задаётся переменной, а таймаут соединения от неё не зависит."""
    monkeypatch.setenv(TIMEOUT_ENV, "600")

    client = DeckForgeClient(base_url="http://service")

    assert client.timeout_s == 600.0
    assert client.http.timeout.connect == CONNECT_TIMEOUT_S
    assert client.http.timeout.read == 600.0


def test_a_broken_number_in_the_environment_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Опечатка в переменной не должна лишать интерфейс таймаута вовсе."""
    monkeypatch.setenv(TIMEOUT_ENV, "почти сразу")

    assert DeckForgeClient(base_url="http://service").timeout_s == TIMEOUT_S


def test_a_lookup_does_not_wait_as_long_as_a_run() -> None:
    """Справочник профилей рисует страницу: у него свой короткий таймаут."""
    assert LOOKUP_TIMEOUT_S < TIMEOUT_S

    seen = timeouts(lambda client: client.profiles())

    assert seen[0]["read"] == LOOKUP_TIMEOUT_S
