"""`VariantProfile` — ось вариативности вёрстки (C7, ARCHITECTURE.md §11).

Три варианта — это три прохода одного графа с разными профилями, а не три пайплайна (ADR-005).
"""

from __future__ import annotations

from pydantic import Field

from deckforge.domain.base import DomainModel
from deckforge.domain.enums import Density, LayoutKind


class VariantProfile(DomainModel):
    variant_id: str = Field(pattern=r"^[A-Z]$")
    name: str
    layout_preference: list[LayoutKind]
    density: Density
    grouping: str = Field(description="by_topic | by_narrative_arc | pyramid")
    data_visual: str = Field(description="table_first | chart_first | kpi_first")
    rationale: str = Field(default="", description="Обоснование оси различий для документации")

    def capacity_ratio(self) -> float:
        """Доля вместимости макета, которую вариант старается занять."""
        return {Density.LOW: 0.45, Density.MEDIUM: 0.7, Density.HIGH: 0.92}[self.density]
