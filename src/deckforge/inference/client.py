"""OpenAI-совместимый клиент к vLLM / VK Inference. Change (8) `inference-client`."""

from __future__ import annotations

from deckforge.config import Settings
from deckforge.registry.models import ModelSpec


class InferenceClient:
    """Один клиент на роль модели (`llm_main`, `llm_fast`, `vlm_judge`, `t2i`).

    Prefix caching: манифест кладётся в общий префикс сообщений, чтобы параллельная
    композиция слайдов переиспользовала KV-кэш (бюджет 100 с, §12).
    """

    def __init__(self, spec: ModelSpec, settings: Settings) -> None:
        self.spec = spec
        self.settings = settings

    async def complete(self, system: str, user: str, **params: object) -> str:
        raise NotImplementedError("change (8) inference-client")
