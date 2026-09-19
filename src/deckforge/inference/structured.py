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
from deckforge.inference.client import (
    Completion,
    InferenceClient,
    InferenceError,
    InferenceTransportError,
)

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
    # Строгий режим требуется провайдерам ещё до модели, поэтому приведение делается
    # здесь, а не в generate_model: так покрыты оба пути — схема, выведенная из доменной
    # модели, и готовая из `prompts/<скилл>/<версия>/schema.json`.
    if response_schema is not None:
        response_schema = strict_schema(response_schema)

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
    overrides: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[T, Completion]:
    """Ответ, валидированный доменной моделью. При провале — цикл починки.

    `overrides` — поля, которые заполняет код, а не модель (вариант, seed, язык).
    Подставляются **до** валидации: иначе ошибка модели в поле, которое код всё равно
    перезапишет, сжигает попытки починки. Прогон 59e0014d2fdc: планировщик трижды
    получил `variant: "report"` и упал, хотя вариант ему известен заранее.
    """
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
            data = _without_nulls(data)
            if overrides and isinstance(data, dict):
                data = {**data, **overrides}
            return model_cls.model_validate(data), completion
        except InferenceTransportError:
            # Провайдер отверг запрос: 404, неверный эндпоинт, модель не поднята.
            # Переспрашивать нечего — ответа не было вовсе. Пробрасываем как есть,
            # иначе транспортный отказ выглядит как «модель не справилась со схемой».
            raise
        except (ValidationError, InferenceError) as exc:
            last_error = exc
            attempt_user = f"{user}\n\n{_repair_hint(exc)}"

    raise InferenceError(
        f"{model_cls.__name__}: ответ не прошёл валидацию за {repairs + 1} попыток: {last_error}"
    )


def strict_schema(schema: dict[str, Any], defs: dict[str, Any] | None = None
                  ) -> dict[str, Any]:
    """Привести схему Pydantic к строгому режиму провайдера.

    Провайдеры со строгой проверкой (Groq, OpenAI) требуют, чтобы `required` перечислял
    **все** свойства объекта. Pydantic же помечает обязательными только те, у которых нет
    значения по умолчанию, — и запрос отвергается ещё до модели:

        400 `required` is required to be supplied and to be an array including every key
        in properties

    Поэтому необязательные поля переносятся в `required`, но им разрешается `null`:
    смысл «поле можно не заполнять» сохраняется, а форма схемы устраивает провайдера.
    """
    if not isinstance(schema, dict):
        return schema

    out = dict(schema)
    defs = defs if defs is not None else (out.get("$defs") or out.get("definitions") or {})

    for key in ("$defs", "definitions", "properties", "patternProperties"):
        if isinstance(out.get(key), dict):
            out[key] = {n: strict_schema(v, defs) for n, v in out[key].items()}
    for key in ("allOf", "prefixItems"):
        if isinstance(out.get(key), list):
            out[key] = [strict_schema(v, defs) for v in out[key]]
    if isinstance(out.get("items"), dict):
        out["items"] = strict_schema(out["items"], defs)

    if isinstance(out.get("anyOf"), list):
        out = _collapse_nullable(out, defs)
        if isinstance(out.get("anyOf"), list):
            out["anyOf"] = [strict_schema(_inline(v, defs), defs) for v in out["anyOf"]]
    if isinstance(out.get("oneOf"), list):
        # Ссылку внутри ветви строгий режим не разворачивает и требует
        # `additionalProperties: false` на самой ветви — встраиваем определение.
        out["oneOf"] = [strict_schema(_inline(v, defs), defs) for v in out["oneOf"]]

    # Строгий режим требует запрета лишних ключей на каждом объекте, включая словари
    # вида `dict[str, X]`, которые Pydantic описывает через additionalProperties-схему.
    if out.get("type") == "object" and "additionalProperties" not in out:
        out["additionalProperties"] = False
    elif isinstance(out.get("additionalProperties"), dict):
        out["additionalProperties"] = strict_schema(out["additionalProperties"], defs)

    properties = out.get("properties")
    if isinstance(properties, dict) and properties:
        was_required = set(out.get("required") or ())
        out["required"] = list(properties)
        out["properties"] = {
            name: prop if name in was_required else _allow_null(prop)
            for name, prop in properties.items()
        }

    return out


def _without_nulls(data: Any) -> Any:
    """Ответ модели без `null`-значений: на их месте сработают умолчания модели.

    Строгий режим разрешает `null` каждому необязательному полю (`strict_schema`), но
    умолчание у поля не всегда `None`: у `SmartArtBlock.color_refs` это пустой список, и
    `null` Pydantic отвергает. Прогон e26f1eb2b6bf: так не собрались 3 слайда из 12.
    Обязательных полей, допускающих `None`, в доменных моделях нет — выбросить `null`
    безопасно: для поля с умолчанием `None` это то же самое.
    """
    if isinstance(data, dict):
        return {k: _without_nulls(v) for k, v in data.items() if v is not None}
    if isinstance(data, list):
        return [_without_nulls(item) for item in data]
    return data


def _inline(branch: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Подставить определение вместо ссылки, если ветвь — голый `$ref`."""
    if isinstance(branch, dict) and set(branch) == {"$ref"}:
        name = branch["$ref"].rsplit("/", 1)[-1]
        return dict(defs.get(name, branch))
    return branch


def _collapse_nullable(prop: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Свернуть `X | None` в одно поле, если `X` — перечисление.

    Pydantic описывает `ColorRef | None` как `anyOf: [{$ref: ColorRef}, {type: null}]`.
    Строгий режим такую пару отвергает: ветви `anyOf` он требует различать либо
    дискриминатором, либо непересекающимся набором ключей, а ссылка на enum и `null`
    не дают ни того, ни другого:

        anyOf branches must be disambiguated via a required discriminator (const/enum)
        or by key-set exclusion with additionalProperties:false

    Разворачиваем ссылку и добавляем `null` прямо в перечисление — смысл тот же,
    а ветвление исчезает.
    """
    branches = prop["anyOf"]
    if len(branches) != 2 or not all(isinstance(b, dict) for b in branches):
        return prop
    nulls = [b for b in branches if b.get("type") == "null"]
    others = [b for b in branches if b.get("type") != "null"]
    if len(nulls) != 1 or len(others) != 1:
        return prop

    target = others[0]
    ref = target.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        target = defs.get(name, target)
    if "enum" not in target:
        return prop

    rest = {k: v for k, v in prop.items() if k != "anyOf"}
    return {
        **rest,
        "type": [target.get("type", "string"), "null"],
        "enum": [*target["enum"], None],
    }


def _allow_null(prop: dict[str, Any]) -> dict[str, Any]:
    """Разрешить `null` там, где поле было необязательным."""
    if not isinstance(prop, dict):
        return prop
    if "null" in str(prop.get("type", "")) or any(
        isinstance(v, dict) and v.get("type") == "null" for v in prop.get("anyOf", [])
    ):
        return prop
    if "anyOf" in prop:
        return {**prop, "anyOf": [*prop["anyOf"], {"type": "null"}]}
    if "type" in prop:
        kind = prop["type"]
        return {**prop, "type": [*kind, "null"] if isinstance(kind, list) else [kind, "null"]}
    # Ссылка на $defs или пустая схема: оборачиваем, не ломая исходное описание.
    return {"anyOf": [prop, {"type": "null"}]}


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


#: Что строгий режим провайдера выразить не может, сколько схему ни приводи.
#: Проверено на Groq 17.09: `dict[str, X]` он требует снабдить
#: `additionalProperties: false`, а это противоречит самой идее словаря с открытым
#: набором ключей. В нашем IR так описаны `SlideIR.fit_report` и `ChartBlock.axis_titles`.
#: Оба поля модель заполнять и не должна: `fit_report` считает слой `layout`, единицы осей
#: берутся из датасета. Схему ответа скилла надо сужать до того, что модель действительно
#: производит, а не выводить целиком из доменной модели.
STRICT_MODE_UNSUPPORTED = ("объекты с открытым набором ключей: dict[str, X]",)
