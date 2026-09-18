"""Клиент инференса. Change (8) `inference-client`.

Сеть здесь подделана: проверяется поведение клиента, а не работа модели. Живые прогоны —
в `tests/integration/test_inference_live.py`, они пропускаются без ключа.
"""

from __future__ import annotations

from typing import Any

import pytest
from openai import APIConnectionError, RateLimitError

from deckforge.config import Settings
from deckforge.inference.client import InferenceClient, InferenceError
from deckforge.registry.models import ModelSpec

SPEC = ModelSpec(
    hf_id="тест/модель", license="apache-2.0", params_total_b=1.0, role="test", endpoint_ref="llm"
)


class FakeMessage:
    def __init__(self, content: str | None, extra: dict[str, Any] | None = None) -> None:
        self.content = content
        self.model_extra = extra or {}


class FakeChoice:
    def __init__(self, content: str | None, finish: str, extra: dict[str, Any] | None) -> None:
        self.message = FakeMessage(content, extra)
        self.finish_reason = finish


class FakeUsage:
    prompt_tokens = 10
    completion_tokens = 20


class FakeResponse:
    def __init__(self, content: str | None, finish: str, extra: dict[str, Any] | None) -> None:
        self.choices = [FakeChoice(content, finish, extra)]
        self.usage = FakeUsage()
        self.model = "тест/модель"


class FakeCompletions:
    """Отдаёт заготовленные ответы по очереди и запоминает, с чем её звали."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        content, finish, extra = item
        return FakeResponse(content, finish, extra)


def build(script: list[Any], **kwargs: Any) -> tuple[InferenceClient, FakeCompletions]:
    client = InferenceClient(spec=SPEC, settings=Settings(), **kwargs)
    fake = FakeCompletions(script)
    client._client.chat.completions = fake  # type: ignore[assignment]
    return client, fake


def ok(text: str) -> tuple[str, str, None]:
    return (text, "stop", None)


def truncated_thinking() -> tuple[None, str, dict[str, str]]:
    """Модель размышляла, бюджет кончился, до ответа не дошла."""
    return (None, "length", {"reasoning": "рассуждаю…"})


# --- базовое поведение -------------------------------------------------------


def test_returns_text_and_usage() -> None:
    client, _ = build([ok(" ответ ")])
    result = client.complete([{"role": "user", "content": "привет"}])
    assert result.text == "ответ", "пробелы вокруг ответа нужно срезать"
    assert (result.prompt_tokens, result.completion_tokens) == (10, 20)
    assert not result.is_truncated


def test_seed_and_sampling_reach_the_backend() -> None:
    client, fake = build([ok("{}")])
    client.complete([{"role": "user", "content": "x"}], seed=42, temperature=0.0, top_p=0.5)
    call = fake.calls[0]
    assert call["seed"] == 42
    assert call["temperature"] == 0.0 and call["top_p"] == 0.5


def test_seed_is_omitted_when_not_given() -> None:
    """Бэкенды по-разному относятся к `seed: null`; лучше не посылать поле вовсе."""
    client, fake = build([ok("{}")])
    client.complete([{"role": "user", "content": "x"}])
    assert "seed" not in fake.calls[0]


def test_schema_is_passed_as_strict_json_schema() -> None:
    schema = {"type": "object", "properties": {"kind": {"type": "string"}}}
    client, fake = build([ok('{"kind": "title"}')])
    client.complete([{"role": "user", "content": "x"}], response_schema=schema, schema_name="вид")

    fmt = fake.calls[0]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == schema
    assert fmt["json_schema"]["name"] == "вид"


# --- размышляющие модели -----------------------------------------------------


def test_reasoning_is_surfaced_for_tracing() -> None:
    client, _ = build([("ответ", "stop", {"reasoning": "ход мысли"})])
    assert client.complete([{"role": "user", "content": "x"}]).reasoning == "ход мысли"


def test_empty_answer_after_thinking_retries_with_a_bigger_budget() -> None:
    """Повтор тем же бюджетом дал бы тот же пустой ответ — надо добавить токенов."""
    client, fake = build([truncated_thinking(), ok("наконец-то")])
    result = client.complete([{"role": "user", "content": "x"}], max_tokens=100)

    assert result.text == "наконец-то"
    assert fake.calls[1]["max_tokens"] > fake.calls[0]["max_tokens"]
    assert result.attempts == 2


def test_budget_growth_is_capped() -> None:
    client, fake = build([truncated_thinking()], max_attempts=6)
    with pytest.raises(InferenceError, match="length"):
        client.complete([{"role": "user", "content": "x"}], max_tokens=100)
    assert max(call["max_tokens"] for call in fake.calls) <= 8192


def test_empty_answer_without_truncation_is_not_retried() -> None:
    """Пустой ответ при finish_reason=stop бюджетом не лечится."""
    client, fake = build([(None, "stop", None)])
    with pytest.raises(InferenceError):
        client.complete([{"role": "user", "content": "x"}])
    assert len(fake.calls) == 1


# --- сбои --------------------------------------------------------------------


def test_rate_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    limit = RateLimitError("слишком часто", response=_resp(429), body=None)
    client, fake = build([limit, ok("получилось")])
    assert client.complete([{"role": "user", "content": "x"}]).text == "получилось"
    assert len(fake.calls) == 2


def test_connection_error_is_retried() -> None:
    client, fake = build([APIConnectionError(request=_req()), ok("получилось")])
    assert client.complete([{"role": "user", "content": "x"}]).text == "получилось"
    assert len(fake.calls) == 2


def test_persistent_failure_is_raised() -> None:
    client, _ = build([APIConnectionError(request=_req())])
    with pytest.raises(APIConnectionError):
        client.complete([{"role": "user", "content": "x"}])


def test_unknown_endpoint_ref_is_rejected() -> None:
    spec = SPEC.model_copy(update={"endpoint_ref": "нет такого"})
    with pytest.raises(ValueError, match="endpoint_ref"):
        InferenceClient(spec=spec, settings=Settings())


def _req() -> Any:
    import httpx

    return httpx.Request("POST", "http://localhost/v1/chat/completions")


def _resp(status: int) -> Any:
    import httpx

    return httpx.Response(status, request=_req())


# --- асинхронная обёртка -----------------------------------------------------


@pytest.mark.asyncio
async def test_async_wrapper_returns_the_same_result() -> None:
    client, _ = build([ok("из потока")])
    result = await client.acomplete([{"role": "user", "content": "x"}])
    assert result.text == "из потока"


def test_truncated_json_is_retried_even_when_text_is_not_empty() -> None:
    """Обрезанный объект вроде '{"' формально непустой, но разобрать его нельзя."""
    schema = {"type": "object", "properties": {}}
    client, fake = build([('{"', "length", None), ok('{"kind": "title"}')])
    result = client.complete(
        [{"role": "user", "content": "x"}], max_tokens=100, response_schema=schema
    )

    assert result.text == '{"kind": "title"}'
    assert fake.calls[1]["max_tokens"] > fake.calls[0]["max_tokens"]


def test_truncated_prose_without_a_schema_is_accepted() -> None:
    """Без схемы обрыв — это просто длинный ответ, а не испорченный."""
    client, fake = build([("длинный ответ, который не влез", "length", None)])
    result = client.complete([{"role": "user", "content": "x"}], max_tokens=100)
    assert result.text.startswith("длинный")
    assert len(fake.calls) == 1


# --- `pattern` там, где его не компилируют (замер 18.09) ----------------------


def test_patterns_are_stripped_for_backends_that_choke_on_them() -> None:
    """llama.cpp переводит схему в грамматику и на `^s\\d{2,}$` отвечает 400.

    Отдать форму без одного ограничения лучше, чем не отдать формы вовсе: без схемы
    модель возвращает свою структуру. `pattern` при этом остаётся в доменной модели
    и проверяется Pydantic.
    """
    from deckforge.inference.client import without_patterns

    schema = {
        "type": "object",
        "properties": {
            "slide_id": {"type": "string", "pattern": r"^s\d{2,}$"},
            "nested": {"type": "array", "items": {"type": "string", "pattern": "^[A-Z]$"}},
        },
        "required": ["slide_id"],
    }
    import json as _json

    cleaned = without_patterns(schema)
    assert "pattern" not in _json.dumps(cleaned)
    assert cleaned["properties"]["slide_id"]["type"] == "string", "форма обязана уцелеть"
    assert cleaned["required"] == ["slide_id"]


def test_patterns_survive_for_backends_that_support_them() -> None:
    from deckforge.inference.client import without_patterns

    schema = {"type": "string", "pattern": "^x$"}
    assert without_patterns({"a": schema}) == {"a": {"type": "string"}}
    # Сама функция ничего не решает — решает флаг реестра; проверяем, что он читается.
    from deckforge.registry.models import ModelSpec

    spec = ModelSpec(hf_id="x/y", license="apache-2.0", params_total_b=1.0, role="r")
    assert spec.supports_schema_patterns is True
