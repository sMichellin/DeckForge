"""Базовый класс всех моделей домена и общие примитивы."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

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

    @model_validator(mode="before")
    @classmethod
    def _drop_computed(cls, data: object) -> object:
        """`right` и `bottom` пишутся в JSON как вычисляемые — при чтении их снимаем.

        Иначе хранимый `BBox` (декор шаблона, `StaticShape.bbox`) не переживал круг
        `model_dump_json` → `model_validate_json`: `extra="forbid"` отвергал собственный
        вывод модели, и манифест с декором не читался ни из кэша, ни из чекпойнта.
        """
        if isinstance(data, dict) and ("right" in data or "bottom" in data):
            return {key: value for key, value in data.items() if key not in ("right", "bottom")}
        return data

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
