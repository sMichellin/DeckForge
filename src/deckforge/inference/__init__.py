"""Слой `inference`: клиент LLM/VLM/T2I, structured output, кэш, ретраи. Change (8).

Промптов здесь нет — они в `prompts/` и загружаются через `deckforge.registry` (C9).
"""

from deckforge.inference.cache import CacheKey, ResponseCache
from deckforge.inference.client import Completion, InferenceClient, InferenceError
from deckforge.inference.factory import client_for, response_cache, vlm_judge
from deckforge.inference.structured import build_messages, generate_json, generate_model
from deckforge.inference.vlm import VlmClient, VlmJudge

__all__ = [
    "CacheKey",
    "Completion",
    "InferenceClient",
    "InferenceError",
    "ResponseCache",
    "VlmClient",
    "VlmJudge",
    "build_messages",
    "client_for",
    "generate_json",
    "generate_model",
    "response_cache",
    "vlm_judge",
]
