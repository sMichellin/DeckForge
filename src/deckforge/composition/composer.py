"""Композиция слайда: подбор макета из манифеста и распределение контента.

Change (11) `slide-composition`. Модель возвращает только валидный `SlideIR` (ADR-001).
"""

from __future__ import annotations

from deckforge.domain.content import ContentPackage
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import SlideIR
from deckforge.domain.template import TemplateManifest
from deckforge.domain.variants import VariantProfile


class SlideComposer:
    def __init__(self, llm_client: object, profile: str | None = None) -> None:
        self.llm = llm_client
        self.profile = profile

    async def compose(
        self,
        slide: SlidePlan,
        content: ContentPackage,
        manifest: TemplateManifest,
        variant: VariantProfile,
        seed: int,
    ) -> SlideIR:
        raise NotImplementedError("change (11) slide-composition")
