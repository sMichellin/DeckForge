"""`DeckPlan` — выход планирования (ARCHITECTURE.md §4.3)."""

from __future__ import annotations

from pydantic import Field, model_validator

from deckforge.domain.base import DomainModel
from deckforge.domain.enums import SlideIntent


class SlidePlan(DomainModel):
    slide_id: str = Field(pattern=r"^s\d{2,}$")
    intent: SlideIntent
    headline: str = Field(
        min_length=1,
        description="Вывод, а не тема. Требование закладывается в промпт планировщика, "
        "проверяется аудитом content.headline_is_conclusion",
    )
    fact_refs: list[str] = Field(default_factory=list)
    dataset_ref: str | None = None
    asset_refs: list[str] = Field(default_factory=list)
    suggested_visual: str | None = Field(
        default=None, description="Например chart:bar, table, smartart:process, kpi"
    )
    speaker_note: str | None = None


class NarrativeCheck(DomainModel):
    one_idea_per_slide: bool = True
    has_arc: bool = True
    notes: list[str] = Field(default_factory=list)


class DeckPlan(DomainModel):
    deck_id: str
    variant: str = Field(pattern=r"^[A-Z]$")
    seed: int
    language: str = "ru"
    slides: list[SlidePlan]
    narrative_check: NarrativeCheck = Field(default_factory=NarrativeCheck)

    @model_validator(mode="after")
    def _unique_slide_ids(self) -> DeckPlan:
        ids = [s.slide_id for s in self.slides]
        if len(ids) != len(set(ids)):
            raise ValueError("slide_id должны быть уникальны в колоде")
        return self

    def slide(self, slide_id: str) -> SlidePlan | None:
        return next((s for s in self.slides if s.slide_id == slide_id), None)
