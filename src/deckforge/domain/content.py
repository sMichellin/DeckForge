"""`ContentPackage` — выход ingestion (ARCHITECTURE.md §4.2)."""

from __future__ import annotations

from pydantic import Field

from deckforge.domain.base import DomainModel


class Number(DomainModel):
    """Число, извлечённое из контента. Якорь фактчекинга `content.numbers_grounded`."""

    value: float
    unit: str | None = None
    raw: str | None = Field(default=None, description="Как было написано в исходнике")


class Fact(DomainModel):
    fact_id: str = Field(pattern=r"^f\d{3,}$")
    text: str
    numbers: list[Number] = Field(default_factory=list)
    source_ref: str | None = Field(default=None, description="Например content.md#L42")
    tags: list[str] = Field(default_factory=list)


class Series(DomainModel):
    name: str
    values: list[float | None]


class Dataset(DomainModel):
    dataset_id: str = Field(pattern=r"^d\d{3,}$")
    title: str
    categories: list[str]
    series: list[Series]
    unit: str | None = None
    source_ref: str | None = None

    @property
    def is_shares(self) -> bool:
        """Похоже на доли целого — подсказка для детерминированного выбора pie/donut."""
        if len(self.series) != 1:
            return False
        values = [v for v in self.series[0].values if v is not None]
        return bool(values) and all(v >= 0 for v in values)


class Asset(DomainModel):
    asset_id: str = Field(pattern=r"^a\d{3,}$")
    kind: str = Field(description="image | logo | chart_image | file")
    path: str
    caption: str | None = None
    width_px: int | None = Field(default=None, gt=0)
    height_px: int | None = Field(default=None, gt=0)


class Brief(DomainModel):
    purpose: str = Field(description="feature | product | project | initiative | report")
    audience: str
    target_slides: int = Field(ge=1, le=60)
    language: str = Field(default="ru", min_length=2, max_length=5)
    tone: str | None = None
    key_message: str | None = None


class ContentPackage(DomainModel):
    brief: Brief
    facts: list[Fact] = Field(default_factory=list)
    datasets: list[Dataset] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    raw_markdown: str | None = Field(default=None, description="Нормализованный исходник")

    def fact(self, fact_id: str) -> Fact | None:
        return next((f for f in self.facts if f.fact_id == fact_id), None)

    def dataset(self, dataset_id: str) -> Dataset | None:
        return next((d for d in self.datasets if d.dataset_id == dataset_id), None)

    def asset(self, asset_id: str) -> Asset | None:
        return next((a for a in self.assets if a.asset_id == asset_id), None)

    @property
    def all_numbers(self) -> list[Number]:
        return [n for f in self.facts for n in f.numbers]
