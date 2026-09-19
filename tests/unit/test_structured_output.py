"""Структурированный вывод и кэш. Change (8) `inference-client`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

from deckforge.inference.cache import ResponseCache
from deckforge.inference.client import Completion, InferenceError
from deckforge.inference.structured import (
    build_messages,
    extract_json,
    generate_json,
    generate_model,
    parse_json,
)


class Verdict(BaseModel):
    kind: str
    score: int = Field(ge=0, le=10)


class ScriptedClient:
    """Подделка `InferenceClient`: отдаёт заготовленные ответы и помнит запросы."""

    model = "тест/модель"

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.requests: list[dict[str, Any]] = []

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        self.requests.append({"messages": messages, **kwargs})
        text = self.answers[min(len(self.requests) - 1, len(self.answers) - 1)]
        return Completion(text=text, model=self.model)


# --- разбор ответа -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"kind": "title"}',
        '```json\n{"kind": "title"}\n```',
        '```\n{"kind": "title"}\n```',
        'Вот ответ:\n{"kind": "title"}\nГотово.',
        '\n\n  {"kind": "title"}  \n',
    ],
)
def test_json_survives_the_wrapping(raw: str) -> None:
    """Даже со строгой схемой модели добавляют ограждение и пояснения вокруг JSON."""
    assert json.loads(extract_json(raw)) == {"kind": "title"}


def test_missing_json_is_a_clear_error() -> None:
    with pytest.raises(InferenceError, match="нет JSON"):
        extract_json("никакого джейсона тут нет")


def test_broken_json_is_a_clear_error() -> None:
    with pytest.raises(InferenceError, match="не разбирается"):
        parse_json('{"kind": "title",}')


def test_array_is_rejected() -> None:
    with pytest.raises(InferenceError, match="объект"):
        parse_json("[1, 2, 3]")


# --- сообщения ---------------------------------------------------------------


def test_system_part_is_separate_for_prefix_caching() -> None:
    """Неизменная часть — отдельным сообщением, иначе KV-кэш бэкенда не переиспользуется."""
    messages = build_messages(system="правила", user="вопрос")
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == "правила"


def test_image_goes_as_a_data_url() -> None:
    """Превью не выкладывается наружу ради одного запроса."""
    messages = build_messages(system="s", user="u", image_png=b"\x89PNG\r\n\x1a\ndata")
    parts = messages[1]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


# --- валидация и починка -----------------------------------------------------


def test_valid_answer_is_parsed_into_the_model() -> None:
    client = ScriptedClient(['{"kind": "title", "score": 7}'])
    result, completion = generate_model(client, Verdict, system="s", user="u")  # type: ignore[arg-type]
    assert result == Verdict(kind="title", score=7)
    assert completion.model == "тест/модель"


def test_invalid_answer_triggers_a_repair_round() -> None:
    """Схема гарантирует форму, но не смысл: 99 — валидный int и невалидный score."""
    client = ScriptedClient(['{"kind": "title", "score": 99}', '{"kind": "title", "score": 5}'])
    result, _ = generate_model(client, Verdict, system="s", user="u")  # type: ignore[arg-type]

    assert result.score == 5
    assert len(client.requests) == 2
    repair_prompt = client.requests[1]["messages"][1]["content"]
    assert "не прошёл проверку" in repair_prompt
    assert "score" in repair_prompt, "модели надо сказать, что именно не так"


def test_repair_shifts_the_seed() -> None:
    """Тот же seed воспроизвёл бы ту же ошибку."""
    client = ScriptedClient(['{"kind": "t", "score": 99}', '{"kind": "t", "score": 1}'])
    generate_model(client, Verdict, system="s", user="u", seed=100)  # type: ignore[arg-type]
    assert [r["seed"] for r in client.requests] == [100, 101]


def test_giving_up_after_the_repair_budget() -> None:
    client = ScriptedClient(['{"kind": "t", "score": 99}'])
    with pytest.raises(InferenceError, match="не прошёл валидацию"):
        generate_model(client, Verdict, system="s", user="u", repairs=1)  # type: ignore[arg-type]
    assert len(client.requests) == 2


def test_schema_defaults_to_the_model_schema() -> None:
    client = ScriptedClient(['{"kind": "t", "score": 1}'])
    generate_model(client, Verdict, system="s", user="u")  # type: ignore[arg-type]
    assert client.requests[0]["response_schema"]["properties"].keys() == {"kind", "score"}


# --- кэш ---------------------------------------------------------------------


def test_cache_hit_avoids_the_call(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    client = ScriptedClient(['{"kind": "title"}'])

    first, c1 = generate_json(client, system="s", user="u", response_schema=None,  # type: ignore[arg-type]
                              seed=1, cache=cache, skill_ref="проба@1.0.0")
    second, c2 = generate_json(client, system="s", user="u", response_schema=None,  # type: ignore[arg-type]
                               seed=1, cache=cache, skill_ref="проба@1.0.0")

    assert first == second
    assert len(client.requests) == 1
    assert c1.from_cache is False and c2.from_cache is True
    assert (cache.hits, cache.misses) == (1, 1)


def test_prompt_version_invalidates_the_cache(tmp_path: Path) -> None:
    """Иначе демо покажет результат предыдущей версии промпта."""
    cache = ResponseCache(tmp_path)
    client = ScriptedClient(['{"a": 1}', '{"a": 2}'])

    generate_json(client, system="s", user="u", response_schema=None, seed=1,  # type: ignore[arg-type]
                  cache=cache, skill_ref="проба@1.0.0")
    generate_json(client, system="s", user="u", response_schema=None, seed=1,  # type: ignore[arg-type]
                  cache=cache, skill_ref="проба@1.1.0")
    assert len(client.requests) == 2


def test_seed_is_part_of_the_key(tmp_path: Path) -> None:
    """Голосование по трём seed не должно трижды получить один кэшированный ответ."""
    cache = ResponseCache(tmp_path)
    client = ScriptedClient(['{"a": 1}', '{"a": 2}', '{"a": 3}'])
    for seed in (1, 2, 3):
        generate_json(client, system="s", user="u", response_schema=None, seed=seed,  # type: ignore[arg-type]
                      cache=cache, skill_ref="проба@1.0.0")
    assert len(client.requests) == 3


def test_disabled_cache_is_transparent(tmp_path: Path) -> None:
    client = ScriptedClient(['{"a": 1}'])
    for _ in range(2):
        generate_json(client, system="s", user="u", response_schema=None,  # type: ignore[arg-type]
                      cache=ResponseCache(None))
    assert len(client.requests) == 2


def test_corrupted_cache_file_is_ignored(tmp_path: Path) -> None:
    """Битый файл кэша не повод падать: спросим модель заново."""
    cache = ResponseCache(tmp_path)
    client = ScriptedClient(['{"a": 1}', '{"a": 1}'])
    generate_json(client, system="s", user="u", response_schema=None, seed=1,  # type: ignore[arg-type]
                  cache=cache, skill_ref="проба@1.0.0")
    for path in tmp_path.rglob("*.json"):
        path.write_text("это не json", encoding="utf-8")

    generate_json(client, system="s", user="u", response_schema=None, seed=1,  # type: ignore[arg-type]
                  cache=cache, skill_ref="проба@1.0.0")
    assert len(client.requests) == 2



# --- транспортный отказ не выдаётся за провал валидации (замер 18.09) ----------


def test_provider_refusal_is_not_repaired(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 перезапускающегося сервера доезжал как «ответ не прошёл валидацию за 3 попыток».

    Переспрашивать модель, которая не отвечала вовсе, бессмысленно: три попытки бьются
    об один и тот же отказ, а причина в сообщении теряется за формулировкой про схему.
    """
    from deckforge.inference.client import InferenceTransportError

    calls = 0

    class RefusingClient:
        model = "fake"

        def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
            nonlocal calls
            calls += 1
            raise InferenceTransportError("fake: 404 Not found")

    with pytest.raises(InferenceTransportError, match="404"):
        generate_model(RefusingClient(), Verdict, system="s", user="u")  # type: ignore[arg-type]

    assert calls == 1, "запрос, отвергнутый провайдером, повторять незачем"


def test_unparsable_answer_is_still_repaired() -> None:
    """Разбор ответа — по-прежнему дело цикла починки: тут модель ответила, просто плохо."""
    answers = ["не json вовсе", json.dumps({"kind": "ok", "score": 7})]

    class SloppyClient:
        model = "fake"

        def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
            return Completion(text=answers.pop(0), model="fake")

    result, _ = generate_model(SloppyClient(), Verdict, system="s", user="u")  # type: ignore[arg-type]
    assert result.score == 7, "со второй попытки ответ должен был разобраться"


def test_null_for_a_field_with_a_non_null_default_is_not_fatal() -> None:
    """Строгий режим разрешает `null`, а умолчание у поля — пустой список (e26f1eb2b6bf)."""
    from deckforge.domain.slide import SmartArtBlock
    from deckforge.inference.structured import _without_nulls

    raw = {
        "block_id": "b02",
        "type": "smartart",
        "pattern": "process",
        "items": ["Разбор", "Сборка"],
        "color_refs": None,
        "x": None,
    }
    block = SmartArtBlock.model_validate(_without_nulls(raw))
    assert block.color_refs == [] and block.bbox is None
