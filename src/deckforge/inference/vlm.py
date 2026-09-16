"""VLM-вызовы: классификация макетов и аудит-судья. Changes (5), (8) и (18).

Протокол отделён от реализации намеренно: слой `parsing` зависит от узкого интерфейса
и тестируется без поднятого инференса, а конкретный клиент подставляется в рантайме.
"""

from __future__ import annotations

from typing import Any, Protocol

from deckforge.inference.cache import ResponseCache
from deckforge.inference.client import InferenceClient
from deckforge.inference.structured import generate_json


class VlmClient(Protocol):
    """Минимум, который нужен вызывающему: спросить про картинку и получить JSON."""

    def ask_image(
        self,
        *,
        system: str,
        user: str,
        image_png: bytes,
        schema: dict[str, Any] | None = None,
        seed: int,
    ) -> dict[str, Any]:
        """Ответ модели, разобранный по схеме.

        Реализация обязана либо вернуть словарь, либо поднять исключение.
        Невалидный JSON наверх не просачивается.
        """
        ...


class VlmJudge:
    """Реализация протокола поверх `InferenceClient`.

    Температура по умолчанию нулевая: разброс между прогонами обеспечивается seed'ом,
    а не случайностью сэмплирования — так голосование меряет неуверенность модели,
    а не шум настроек.
    """

    def __init__(
        self,
        client: InferenceClient,
        *,
        cache: ResponseCache | None = None,
        skill_ref: str = "vlm",
        max_tokens: int = 3072,
        temperature: float = 0.0,
    ) -> None:
        self.client = client
        self.cache = cache
        self.skill_ref = skill_ref
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.calls = 0

    def ask_image(
        self,
        *,
        system: str,
        user: str,
        image_png: bytes,
        schema: dict[str, Any] | None = None,
        seed: int,
    ) -> dict[str, Any]:
        self.calls += 1
        data, _ = generate_json(
            self.client,
            system=system,
            user=user,
            response_schema=schema,
            seed=seed,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            schema_name="verdict",
            skill_ref=self.skill_ref,
            cache=self.cache,
            image_png=image_png,
        )
        return data
