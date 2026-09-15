"""`SlideIR` — выход композиции, единственный вход рендерера (ARCHITECTURE.md §4.4).

LLM производит **только** эту структуру. Она валидируется до того, как будет создан файл (ADR-001).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from deckforge.domain.base import BBox, DomainModel
from deckforge.domain.enums import (
    ChartType,
    ColorRef,
    ImageFit,
    ImageSource,
    SmartArtPattern,
    TextRole,
)


class _Positioned(DomainModel):
    """Координаты в EMU. Если не заданы — берутся из плейсхолдера макета."""

    x: int | None = Field(default=None, ge=0)
    y: int | None = Field(default=None, ge=0)
    cx: int | None = Field(default=None, gt=0)
    cy: int | None = Field(default=None, gt=0)

    @property
    def bbox(self) -> BBox | None:
        if None in (self.x, self.y, self.cx, self.cy):
            return None
        return BBox(x=self.x, y=self.y, cx=self.cx, cy=self.cy)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _all_or_nothing(self) -> _Positioned:
        given = [v is not None for v in (self.x, self.y, self.cx, self.cy)]
        if any(given) and not all(given):
            raise ValueError("координаты задаются целиком (x, y, cx, cy) либо не задаются вовсе")
        return self


class TextBlock(_Positioned):
    block_id: str
    type: Literal["text"] = "text"
    placeholder_idx: int | None = Field(default=None, ge=0)
    role: TextRole
    text: str
    color_ref: ColorRef | None = None
    size_pt: float | None = Field(default=None, gt=0, description="Только из шкалы шаблона")


class BulletItem(DomainModel):
    text: str
    level: int = Field(default=0, ge=0, le=4)


class BulletsBlock(_Positioned):
    block_id: str
    type: Literal["bullets"] = "bullets"
    placeholder_idx: int | None = Field(default=None, ge=0)
    role: TextRole = TextRole.BODY
    items: list[BulletItem] = Field(min_length=1)
    max_level: int = Field(default=1, ge=0, le=4)
    size_pt: float | None = Field(default=None, gt=0)


class ChartBlock(_Positioned):
    block_id: str
    type: Literal["chart"] = "chart"
    chart_type: ChartType
    dataset_ref: str
    axis_titles: dict[str, str] = Field(default_factory=dict)
    legend: bool = True
    data_labels: bool = True
    series_color_refs: list[ColorRef] = Field(default_factory=list)


class TableBlock(_Positioned):
    block_id: str
    type: Literal["table"] = "table"
    dataset_ref: str | None = None
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    first_row_header: bool = True
    banding: bool = True


class SmartArtBlock(_Positioned):
    block_id: str
    type: Literal["smartart"] = "smartart"
    pattern: SmartArtPattern
    items: list[str] = Field(min_length=2)
    color_refs: list[ColorRef] = Field(default_factory=list)


class IconBlock(_Positioned):
    block_id: str
    type: Literal["icon"] = "icon"
    query: str = Field(description="Имя иконки в библиотеке Lucide/Tabler")
    color_ref: ColorRef | None = None


class ImageBlock(_Positioned):
    block_id: str
    type: Literal["image"] = "image"
    source: ImageSource
    asset_ref: str | None = None
    prompt: str | None = None
    fit: ImageFit = ImageFit.COVER
    alt_text: str | None = None

    @model_validator(mode="after")
    def _source_consistency(self) -> ImageBlock:
        if self.source == ImageSource.ASSET and not self.asset_ref:
            raise ValueError("source=asset требует asset_ref")
        if self.source == ImageSource.GENERATED and not self.prompt:
            raise ValueError("source=generated требует prompt")
        return self


class KpiItem(DomainModel):
    value: str
    label: str
    color_ref: ColorRef | None = None


class KpiBlock(_Positioned):
    block_id: str
    type: Literal["kpi"] = "kpi"
    items: list[KpiItem] = Field(min_length=1, max_length=6)


Block = Annotated[
    TextBlock
    | BulletsBlock
    | ChartBlock
    | TableBlock
    | SmartArtBlock
    | IconBlock
    | ImageBlock
    | KpiBlock,
    Field(discriminator="type"),
]


class Provenance(DomainModel):
    fact_refs: list[str] = Field(default_factory=list)
    prompt_version: str | None = Field(default=None, description="skill@semver")
    model: str | None = None
    seed: int | None = None


class FitResult(DomainModel):
    final_size_pt: float = Field(gt=0)
    overflow: bool = False
    lines: int | None = Field(default=None, ge=0)
    required_cy_emu: int | None = Field(default=None, ge=0)
    strategy: str | None = Field(default=None, description="as_is | shrink | shorten | split")


class SlideIR(DomainModel):
    slide_id: str
    layout_id: str
    variant: str = Field(pattern=r"^[A-Z]$")
    blocks: list[Block]
    speaker_note: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)
    fit_report: dict[str, FitResult] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_block_ids(self) -> SlideIR:
        ids = [b.block_id for b in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("block_id должны быть уникальны в пределах слайда")
        return self

    def block(self, block_id: str) -> Block | None:
        return next((b for b in self.blocks if b.block_id == block_id), None)


class DeckIR(DomainModel):
    """Колода целиком: то, что уходит в рендерер и экспорт."""

    deck_id: str
    variant: str = Field(pattern=r"^[A-Z]$")
    template_id: str
    language: str = "ru"
    seed: int
    slides: list[SlideIR]
