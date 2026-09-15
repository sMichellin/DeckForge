"""Вставка изображений с `fit: cover/contain` без искажения пропорций. Change (13)/(24)."""

from __future__ import annotations

from deckforge.domain.content import ContentPackage
from deckforge.domain.slide import ImageBlock


def add_image(slide: object, block: ImageBlock, content: ContentPackage) -> object:
    raise NotImplementedError("change (13) pptx-writer")
