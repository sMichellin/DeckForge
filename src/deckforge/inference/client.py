"""OpenAI-совместимый клиент. Change (8) `inference-client`.

Один код работает и с локальным vLLM, и с роутером HuggingFace, и с инференсом VK:
все трое говорят по протоколу OpenAI. Меняется только `base_url` в окружении.

Два обстоятельства, которые пришлось учесть после проверки на живом роутере:

* **Модели рассуждают.** Qwen3.x отдают размышление в отдельном поле, а `content`
  остаётся пустым, пока бюджет токенов не позволит дойти до ответа. Отключить
  размышление через роутер нельзя (`chat_template_kwargs` он не принимает), поэтому
  пустой ответ с `finish_reason="length"` — это не сбой, а сигнал добавить бюджет.
* **Ответ приходит с пробельным мусором** вокруг JSON даже при строгой схеме.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from deckforge.config import Settings, get_settings
from deckforge.registry.models import ModelSpec

#: Ошибки, которые проходят сами: лимит запросов, обрыв связи, таймаут, 5xx.
RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)

#: Коды 4xx, которые всё-таки стоит повторить: это не «запрос плохой», а «сейчас занято».
_RETRYABLE_4XX = frozenset({408, 409, 425, 429})

#: Кончились кредиты или доступ закрыт — повторять бессмысленно и вредно.
_QUOTA_CODES = frozenset({402, 403})

#: Некоторые провайдеры отдают размышление прямо в тексте ответа.
_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)

#: Во сколько раз поднимается бюджет токенов, если модель не дошла до ответа.
_BUDGET_GROWTH = 3

#: Выше этого не поднимаемся: если ответа нет и на таком бюджете, дело не в бюджете.
_MAX_TOKENS_CAP = 8192


class InferenceError(RuntimeError):
    """Модель не дала пригодного ответа. Отдельный тип, чтобы отличать от сетевых сбоев."""


class InferenceTransportError(InferenceError):
    """Отказ провайдера: 404, 400, неверный эндпоинт, модель не поднята.

    Отдельный тип нужен циклу починки в `structured.py`: тот переспрашивает **модель**,
    когда её ответ не разобрался, и повторять запрос, который провайдер отверг, ему
    бессмысленно. Хуже того, без этого различия транспортный отказ доезжает
    до пользователя под видом «ответ не прошёл валидацию» — так 404 перезапускавшегося
    сервера выглядел как проблема схемы (замер 18.09).
    """


class InferenceQuotaError(InferenceError):
    """Квота исчерпана.

    Отдельный тип нужен, чтобы вызывающий прекратил попытки, а не продолжал стучаться:
    кончившиеся кредиты не восстановятся к следующему макету, и тридцать таких вызовов —
    это тридцать секунд впустую и молчаливый откат на эвристику.
    """


@dataclass(frozen=True, slots=True)
class Completion:
    """Ответ модели вместе с тем, что нужно для трейса и бюджета."""

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = "stop"
    reasoning: str | None = None
    attempts: int = 1
    from_cache: bool = False

    @property
    def is_truncated(self) -> bool:
        return self.finish_reason == "length"


@dataclass(frozen=True, slots=True)
class Endpoint:
    base_url: str
    api_key: str


def endpoints_from(settings: Settings) -> dict[str, Endpoint]:
    """`endpoint_ref` модели → куда идти. Секреты берутся только из окружения."""
    return {
        "llm": Endpoint(settings.llm_base_url, settings.llm_api_key),
        "vlm": Endpoint(settings.vlm_base_url, settings.vlm_api_key),
        "t2i": Endpoint(settings.t2i_base_url, settings.t2i_api_key),
    }


@dataclass
class InferenceClient:
    """Клиент одной роли модели (`llm_main`, `llm_fast`, `vlm_judge`, `t2i`).

    Prefix caching: неизменная часть (манифест, правила) кладётся в системное сообщение
    и не меняется между слайдами — так бэкенд переиспользует KV-кэш и композиция
    укладывается в бюджет 100 с (§12).
    """

    spec: ModelSpec
    settings: Settings = field(default_factory=get_settings)
    timeout_s: float = 120.0
    max_attempts: int = 3

    def __post_init__(self) -> None:
        endpoint = endpoints_from(self.settings).get(self.spec.endpoint_ref or "llm")
        if endpoint is None:
            raise ValueError(f"неизвестный endpoint_ref: {self.spec.endpoint_ref!r}")
        self._client = OpenAI(
            base_url=endpoint.base_url, api_key=endpoint.api_key, timeout=self.timeout_s
        )

    @property
    def model(self) -> str:
        return self.spec.endpoint_model_id

    # --- вызов -------------------------------------------------------------

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        top_p: float = 0.95,
        seed: int | None = None,
        response_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
    ) -> Completion:
        """Один осмысленный ответ модели.

        Сетевые сбои повторяются с отступом; обрыв по бюджету токенов — отдельно,
        с увеличенным бюджетом, потому что повтор тем же бюджетом даст то же самое.

        Обрыв опасен вдвойне, когда ждём JSON: обрезанный объект (`{"`) формально
        непустой, но разобрать его нельзя. Поэтому при заданной схеме бюджет добирается
        на любом обрыве, а не только на пустом ответе.
        """
        budget = max_tokens
        last: Completion | None = None

        for attempt in range(1, self.max_attempts + 1):
            last = self._call(
                messages,
                max_tokens=budget,
                temperature=temperature,
                top_p=top_p,
                seed=seed,
                response_schema=response_schema,
                schema_name=schema_name,
                attempts=attempt,
            )
            truncated_json = last.is_truncated and response_schema is not None
            if last.text and not truncated_json:
                return last
            if not last.is_truncated or budget >= _MAX_TOKENS_CAP:
                break
            # Размышление съело весь бюджет — до ответа модель не дошла.
            budget = min(_MAX_TOKENS_CAP, budget * _BUDGET_GROWTH)

        reason = "пустой ответ" if last is None else f"finish_reason={last.finish_reason}"
        if last is not None and last.text:
            reason = f"{reason}, ответ оборван на {len(last.text)} знаках"
        raise InferenceError(f"{self.model}: {reason} после {self.max_attempts} попыток")

    async def acomplete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        """Асинхронная обёртка для узлов графа.

        Клиент OpenAI потокобезопасен, а нагрузка сетевая, поэтому отдельного
        асинхронного клиента здесь не нужно — достаточно вынести вызов из цикла событий.
        """
        return await asyncio.to_thread(lambda: self.complete(messages, **kwargs))

    @retry(
        retry=retry_if_exception_type(RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        reraise=True,
    )
    def _call(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        seed: int | None,
        response_schema: dict[str, Any] | None,
        schema_name: str,
        attempts: int,
    ) -> Completion:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }
        if seed is not None:
            params["seed"] = seed
        # Провайдер без поддержки JSON Schema отвергнет запрос целиком, поэтому схема
        # в таком случае остаётся только в тексте промпта, а форму держит цикл починки.
        if response_schema is not None and self.spec.supports_structured_output:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": response_schema,
                },
            }

        try:
            response = self._client.chat.completions.create(**params)
        except APIStatusError as exc:
            # 4xx повторять бессмысленно: запрос не станет валиднее сам по себе.
            # Исключение — коды занятости: там повтор как раз и помогает.
            if exc.status_code in _QUOTA_CODES:
                raise InferenceQuotaError(
                    f"{self.model}: {exc.status_code} — квота исчерпана или доступ закрыт"
                ) from exc
            if exc.status_code < 500 and exc.status_code not in _RETRYABLE_4XX:
                raise InferenceTransportError(
                    f"{self.model}: {exc.status_code} {exc.message}"
                ) from exc
            raise

        choice = response.choices[0]
        message = choice.message
        extra = message.model_extra or {}
        usage = response.usage

        return Completion(
            text=_THINK_BLOCK.sub("", message.content or "").strip(),
            model=response.model or self.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            finish_reason=choice.finish_reason or "stop",
            reasoning=extra.get("reasoning") or extra.get("reasoning_content"),
            attempts=attempts,
        )
