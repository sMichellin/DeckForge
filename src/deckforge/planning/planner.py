"""Состав и порядок слайдов. Change (10) `deck-planning`.

Заголовок обязан быть **выводом**, а не темой: требование закладывается в промпт
`deck_planner`, а не чинится авто-фиксом после.
"""

from __future__ import annotations

from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import DeckPlan
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile


class DeckPlanner:
    """Один вызов LLM на всю колоду — бюджет 35 с (§12)."""

    def __init__(self, llm_client: object, profile: str | None = None) -> None:
        self.llm = llm_client
        self.profile = profile

    async def plan(
        self,
        content: ContentPackage,
        manifest: TemplateManifest,
        variant: VariantProfile,
        seed: int,
    ) -> DeckPlan:
        """Промпт получает только *доступные виды макетов* манифеста, не сам шаблон."""
        raise NotImplementedError("change (10) deck-planning")
