"""Клиент сервиса. Change (23) `web-ui`.

Интерфейс говорит с бэкендом **только по HTTP** и ничего из `deckforge` не импортирует.
Это не чистоплюйство: `frontend/` монтируется в свой контейнер отдельным томом
(`docker/compose.yaml`), и связывать его сборку со сборкой пакета незачем. Контракт
между ними — сам API, он описан в `openspec/changes/service-api/proposal.md`.

Все адреса собраны здесь. Разъехаться с сервером они могут — но в одном месте,
а не в пяти местах разметки.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://app:8080"
#: Долгая генерация — не повод ждать её в одном запросе: ждём мы опросом статуса.
#: Но ждать ответа долго — нормально: стенд держит прогон в цикле событий API, а на
#: рабочей топологии один слот инференса означает очередь. 30 с не хватало, и `final`
#: с тремя вариантами и судьёй-VLM отдавал человеку `ReadTimeout` вместо статуса.
TIMEOUT_S = 180.0
#: Мёртвый адрес видно сразу: соединение либо устанавливается быстро, либо не устанавливается.
CONNECT_TIMEOUT_S = 5.0
#: Справочники рисуют страницу на каждый щелчок — ждать на них нечего.
LOOKUP_TIMEOUT_S = 10.0
#: Терпение к занятому серверу — число стенда, а не пакета: пересобирать образ ради него
#: незачем.
TIMEOUT_ENV = "DECKFORGE_UI_TIMEOUT_S"


def default_timeout_s() -> float:
    """Долгий таймаут чтения: из окружения, а нет его — умолчание пакета."""
    try:
        return float(os.environ[TIMEOUT_ENV])
    except (KeyError, ValueError):
        return TIMEOUT_S


class ServiceError(RuntimeError):
    """Сервис ответил отказом. Причина — то, что он написал, а не наш пересказ."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


@dataclass(slots=True)
class DeckForgeClient:
    """Тонкая обёртка над HTTP. Ни одного решения, кроме разбора ответа."""

    base_url: str = DEFAULT_BASE_URL
    timeout_s: float = field(default_factory=default_timeout_s)
    _http: httpx.Client | None = None

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            timeout = httpx.Timeout(self.timeout_s, connect=CONNECT_TIMEOUT_S)
            self._http = httpx.Client(base_url=self.base_url, timeout=timeout)
        return self._http

    # --- справочники ---------------------------------------------------------

    def profiles(self) -> list[str]:
        """Профили прогона. Пустой список — сервис недоступен или их нет.

        Отказ здесь не ошибка пользователя: список нужен, чтобы наполнить выпадашку,
        и без него интерфейс обязан остаться живым. Иначе упавший сервис не даст
        даже исправить адрес, по которому до него стучатся.
        """
        try:
            payload = self._json(self.http.get("/profiles", timeout=LOOKUP_TIMEOUT_S))
        except Exception:
            return []
        names = payload.get("profiles") if isinstance(payload, dict) else None
        return [str(name) for name in names or []]

    # --- прогон --------------------------------------------------------------

    def create_run(self, **fields: Any) -> str:
        return str(self._json(self.http.post("/runs", json=fields))["run_id"])

    def upload_template(self, run_id: str, name: str, data: bytes) -> None:
        self._ok(
            self.http.put(
                f"/runs/{run_id}/template", params={"filename": name}, content=data
            )
        )

    def upload_content(self, run_id: str, name: str, data: bytes) -> None:
        self._ok(self.http.put(f"/runs/{run_id}/content/{name}", content=data))

    def start(self, run_id: str) -> None:
        self._ok(self.http.post(f"/runs/{run_id}/start"))

    # --- наблюдение ----------------------------------------------------------

    def status(self, run_id: str) -> dict[str, Any]:
        return self._json(self.http.get(f"/runs/{run_id}"))

    def findings(self, run_id: str) -> list[dict[str, Any]]:
        payload = self._json(self.http.get(f"/runs/{run_id}/findings"))
        return list(payload) if isinstance(payload, list) else []

    def report(self, run_id: str) -> dict[str, Any] | None:
        """Отчёт или `None`, если его ещё нет. Это не ошибка, а «рано».

        Сервис отвечает 409, и показывать пользователю красное сообщение о том,
        что прогон ещё идёт, незачем.
        """
        answer = self.http.get(f"/runs/{run_id}/report")
        if answer.status_code == 409:
            return None
        return self._json(answer)

    def preview(self, run_id: str, slide_id: str) -> bytes | None:
        answer = self.http.get(f"/runs/{run_id}/previews/{slide_id}")
        if answer.status_code == 404:
            return None
        self._ok(answer)
        return answer.content

    def example(self, run_id: str, recipe_id: str) -> bytes | None:
        """Превью слайда-примера шаблона; нет в кэше — `None`, лист покажет слайд без него."""
        answer = self.http.get(f"/runs/{run_id}/examples/{recipe_id}")
        if answer.status_code == 404:
            return None
        self._ok(answer)
        return answer.content

    # --- действия ------------------------------------------------------------

    def choose_fixes(self, run_id: str, finding_ids: list[str]) -> None:
        self._ok(self.http.post(f"/runs/{run_id}/fixes", json={"finding_ids": finding_ids}))

    def export(self, run_id: str, fmt: str) -> bytes | None:
        answer = self.http.get(f"/runs/{run_id}/exports/{fmt}")
        if answer.status_code in (404, 409):
            return None
        self._ok(answer)
        return answer.content

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    # --- разбор --------------------------------------------------------------

    def _ok(self, answer: httpx.Response) -> httpx.Response:
        if answer.is_success:
            return answer
        raise ServiceError(answer.status_code, _detail(answer))

    def _json(self, answer: httpx.Response) -> Any:
        return self._ok(answer).json()


def _detail(answer: httpx.Response) -> str:
    """Текст отказа. Сервис отвечает `{"detail": …}`, но падать на этом нельзя."""
    try:
        payload = answer.json()
    except ValueError:
        return answer.text.strip() or answer.reason_phrase
    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])
    return str(payload)
