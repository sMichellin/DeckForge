"""Структурированный вывод по JSON Schema. Change (8) `inference-client`.

Схема идёт в `response_format` бэкенда: и vLLM (XGrammar), и роутер HuggingFace
принимают `json_schema` и держат формат сами. Валидация Pydantic остаётся поверх —
схема гарантирует форму, но не осмысленность: `layout_id`, которого нет в манифесте,
формально валиден.

Цикл починки: невалидный ответ возвращается модели вместе с текстом ошибки. Это дешевле
полной перегенерации и обычно хватает одной итерации.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from deckforge.inference.cache import ResponseCache
from deckforge.inference.client import Completion, InferenceClient, InferenceError

#: Модели любят обернуть JSON в ```json … ``` даже при строгой схеме.
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def extract_json(text: str) -> str:
    """Достать JSON из ответа: убрать ограждение и текст вокруг объекта."""
    cleaned = _FENCE.sub("", text).strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise InferenceError(f"в ответе нет JSON-объекта: {cleaned[:200]!r}")
    return cleaned[start : end + 1]


def parse_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(extract_json(text))
    except json.JSONDecodeError as exc:
        raise InferenceError(f"ответ не разбирается как JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InferenceError("ожидался JSON-объект, а не массив или скаляр")
    return data


def generate_json(
    client: InferenceClient,
    *,
    system: str,
    user: str,
    response_schema: dict[str, Any] | None,
    seed: int | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    top_p: float = 0.95,
    schema_name: str = "response",
    skill_ref: str = "unknown",
    cache: ResponseCache | None = None,
    image_png: bytes | None = None,
) -> tuple[dict[str, Any], Completion]:
    """Ответ модели, разобранный в словарь. Кэш прозрачен для вызывающего."""
    messages = build_messages(system=system, user=user, image_png=image_png)

    if cache is not None and cache.enabled:
        key = cache.key(
            model=client.model,
            skill_ref=skill_ref,
            seed=seed,
            messages=messages,
            response_schema=response_schema,
        )
        if (cached := cache.get(key)) is not None:
            return parse_json(cached), Completion(
                text=cached, model=client.model, from_cache=True
            )
    else:
        key = None

    completion = client.complete(
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        seed=seed,
        response_schema=response_schema,
        schema_name=schema_name,
    )
    data = parse_json(completion.text)

    if cache is not None and key is not None:
        cache.put(key, completion.text, {"model": completion.model, "skill": skill_ref})
    return data, completion


def generate_model[T: BaseModel](
    client: InferenceClient,
    model_cls: type[T],
    *,
    system: str,
    user: str,
    response_schema: dict[str, Any] | None = None,
    seed: int | None = None,
    repairs: int = 2,
    **kwargs: Any,
) -> tuple[T, Completion]:
    """Ответ, валидированный доменной моделью. При провале — цикл починки."""
    schema = response_schema if response_schema is not None else model_cls.model_json_schema()
    attempt_user = user
    last_error: Exception | None = None

    for attempt in range(repairs + 1):
        try:
            data, completion = generate_json(
                client,
                system=system,
                user=attempt_user,
                response_schema=schema,
                # Тот же seed повторил бы ту же ошибку, поэтому на починке он сдвигается.
                seed=None if seed is None else seed + attempt,
                schema_name=model_cls.__name__,
                **kwargs,
            )
            return model_cls.model_validate(data), completion
        except (ValidationError, InferenceError) as exc:
            last_error = exc
            attempt_user = f"{user}\n\n{_repair_hint(exc)}"

    raise InferenceError(
        f"{model_cls.__name__}: ответ не прошёл валидацию за {repairs + 1} попыток: {last_error}"
    )


def _repair_hint(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        problems = "\n".join(
            f"- поле {'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()[:8]
        )
        return f"Предыдущий ответ не прошёл проверку:\n{problems}\nИсправь и верни JSON заново."
    return f"Предыдущий ответ не удалось разобрать: {exc}. Верни строго JSON по схеме."


def build_messages(
    *, system: str, user: str, image_png: bytes | None = None
) -> list[dict[str, Any]]:
    """Сообщения в формате OpenAI.

    Системная часть идёт отдельным сообщением и не меняется между слайдами — на этом
    держится prefix caching (§12). Картинка кладётся data-URL'ом: внешний хостинг
    превью ради одного запроса не нужен и утёк бы наружу.
    """
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    if image_png is None:
        messages.append({"role": "user", "content": user})
        return messages

    import base64

    encoded = base64.b64encode(image_png).decode("ascii")
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        }
    )
    return messages
