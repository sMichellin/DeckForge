"""Классификация макетов: эвристика по плейсхолдерам + VLM по превью.

Change (5) `layout-classification`. Никаких списков имён макетов конкретных шаблонов (C6).
"""

from __future__ import annotations

from deckforge.domain.enums import LayoutKind
from deckforge.domain.template import LayoutSpec


def classify_heuristic(layout: LayoutSpec) -> tuple[LayoutKind, float]:
    """Тип по составу и геометрии плейсхолдеров. Дёшево, работает всегда."""
    raise NotImplementedError("change (5) layout-classification")


def classify(layout: LayoutSpec, preview_png: bytes | None = None) -> tuple[LayoutKind, float, str]:
    """Гибрид: эвристика, затем VLM на спорных случаях (низкая уверенность)."""
    raise NotImplementedError("change (5) layout-classification")
