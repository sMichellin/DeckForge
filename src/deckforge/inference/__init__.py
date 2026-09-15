"""Слой `inference`: клиент LLM/VLM/T2I, structured output, кэш, ретраи. Change (8).

Промптов здесь нет — они в `prompts/` и загружаются через `deckforge.registry` (C9).
"""

from deckforge.inference.client import InferenceClient
from deckforge.inference.structured import generate_structured

__all__ = ["InferenceClient", "generate_structured"]
