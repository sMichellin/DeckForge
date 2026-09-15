"""Guided decoding по JSON Schema. Change (8) `inference-client`.

Модель физически не может вернуть невалидный `SlideIR`: схема передаётся в
`response_format`/`guided_json` бэкенда. При отказе — 2 ретрая, затем деградация
до упрощённого макета (§15).
"""

from __future__ import annotations

from pydantic import BaseModel

from deckforge.inference.client import InferenceClient


async def generate_structured[T: BaseModel](
    client: InferenceClient,
    model_cls: type[T],
    system: str,
    user: str,
    *,
    seed: int,
    retries: int = 2,
) -> T:
    raise NotImplementedError("change (8) inference-client")
