"""Подбор макета: намерение слайда + предпочтения варианта + вместимость.

Change (11) `slide-composition`. Цепочка деградации: сложный макет → простой из того же шаблона.
"""

from __future__ import annotations

from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import LayoutSpec, TemplateManifest
from deckforge.domain.variants import VariantProfile


def pick_layout(
    slide: SlidePlan, manifest: TemplateManifest, variant: VariantProfile
) -> LayoutSpec:
    raise NotImplementedError("change (11) slide-composition")
