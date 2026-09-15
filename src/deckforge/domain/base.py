"""Базовый класс всех моделей домена и общие примитивы."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field

from deckforge.domain.units import Emu


class DomainModel(BaseModel):
    """Строгая модель: лишние поля запрещены, значения иммутабельны после валидации."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        use_enum_values=False,
        str_strip_whitespace=True,
    )


class BBox(DomainModel):
    """Прямоугольник в EMU. Origin — левый верхний угол слайда."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    cx: int = Field(gt=0)
    cy: int = Field(gt=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def right(self) -> int:
        return self.x + self.cx

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bottom(self) -> int:
        return self.y + self.cy

    @property
    def area(self) -> int:
        return self.cx * self.cy

    def intersection_area(self, other: BBox) -> int:
        dx = min(self.right, other.right) - max(self.x, other.x)
        dy = min(self.bottom, other.bottom) - max(self.y, other.y)
        return dx * dy if dx > 0 and dy > 0 else 0

    def contains(self, other: BBox) -> bool:
        return (
            other.x >= self.x
            and other.y >= self.y
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def as_tuple(self) -> tuple[Emu, Emu, Emu, Emu]:
        return (Emu(self.x), Emu(self.y), Emu(self.cx), Emu(self.cy))
