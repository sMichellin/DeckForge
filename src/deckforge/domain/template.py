"""`TemplateManifest` — выход слоя parsing (ARCHITECTURE.md §4.1).

Самодостаточный артефакт: слои выше него не имеют доступа к исходному .pptx (ADR-003).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from deckforge.domain.base import BBox, DomainModel
from deckforge.domain.enums import ColorRef, FontRef, LayoutKind, TextRole

HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class SlideSize(DomainModel):
    cx_emu: int = Field(gt=0)
    cy_emu: int = Field(gt=0)
    aspect: str = Field(description="Например 16:9, 4:3")

    @property
    def bbox(self) -> BBox:
        return BBox(x=0, y=0, cx=self.cx_emu, cy=self.cy_emu)


class ThemeColors(DomainModel):
    """Все 12 цветов clrScheme. Отсутствие любого — ошибка парсера, не значение по умолчанию."""

    dk1: str = Field(pattern=HEX_COLOR)
    lt1: str = Field(pattern=HEX_COLOR)
    dk2: str = Field(pattern=HEX_COLOR)
    lt2: str = Field(pattern=HEX_COLOR)
    accent1: str = Field(pattern=HEX_COLOR)
    accent2: str = Field(pattern=HEX_COLOR)
    accent3: str = Field(pattern=HEX_COLOR)
    accent4: str = Field(pattern=HEX_COLOR)
    accent5: str = Field(pattern=HEX_COLOR)
    accent6: str = Field(pattern=HEX_COLOR)
    hlink: str = Field(pattern=HEX_COLOR)
    folHlink: str = Field(pattern=HEX_COLOR)

    def get(self, ref: ColorRef) -> str:
        return getattr(self, ref.value)  # type: ignore[no-any-return]


class ThemeFonts(DomainModel):
    major_latin: str
    minor_latin: str
    major_cs: str | None = None
    minor_cs: str | None = None

    def get(self, ref: FontRef) -> str | None:
        return getattr(self, ref.value)  # type: ignore[no-any-return]


class Theme(DomainModel):
    colors: ThemeColors
    fonts: ThemeFonts


class TypographyStep(DomainModel):
    """Ступень типографической шкалы. Выводится из шаблона, не задаётся константами."""

    role: TextRole
    size_pt: float = Field(gt=0)
    font_ref: FontRef
    bold: bool = False
    italic: bool = False
    color_ref: ColorRef
    line_spacing: float | None = Field(default=None, gt=0)


class Margins(DomainModel):
    left: int = Field(ge=0)
    right: int = Field(ge=0)
    top: int = Field(ge=0)
    bottom: int = Field(ge=0)


class Grid(DomainModel):
    margins_emu: Margins
    guides_x_emu: list[int] = Field(default_factory=list)
    guides_y_emu: list[int] = Field(default_factory=list)
    columns: int = Field(default=12, gt=0)
    gutter_emu: int = Field(default=0, ge=0)
    guides_source: str = Field(
        default="xml",
        description="xml — направляющие есть в мастере; inferred — выведены кластеризацией",
    )


class PlaceholderSpec(DomainModel):
    idx: int = Field(ge=0)
    ph_type: str = Field(description="TITLE | BODY | PICTURE | CHART | TABLE | ...")
    role: TextRole | None = None
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    cx: int = Field(gt=0)
    cy: int = Field(gt=0)

    @property
    def bbox(self) -> BBox:
        return BBox(x=self.x, y=self.y, cx=self.cx, cy=self.cy)


class LayoutCapacity(DomainModel):
    """Вместимость макета. Вычисляется по метрикам шрифта и площади, не константами."""

    max_bullets: int = Field(ge=0)
    max_chars_body: int = Field(ge=0)
    max_chars_title: int = Field(ge=0)
    supports_chart: bool = False
    supports_table: bool = False
    supports_image: bool = False


class ShapeKind(StrEnum):
    """Что за фигура. Тип важен для классификации: картинка во весь слайд и текстовый
    блок того же размера означают совершенно разные макеты."""

    PICTURE = "picture"
    TEXT = "text"
    SHAPE = "shape"
    CHART = "chart"
    TABLE = "table"


class LayoutShape(DomainModel):
    """Фигура макета **вне** плейсхолдеров.

    Шаблоны сплошь и рядом кладут фон, фотографию или декоративный знак обычной фигурой,
    а не плейсхолдером. Для наполнения такая фигура бесполезна — в неё ничего не положить, —
    но для понимания макета необходима: без неё «Паттерн + фото» выглядит как пустой слайд
    с заголовком.
    """

    shape_id: str
    kind: ShapeKind
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    cx: int = Field(gt=0)
    cy: int = Field(gt=0)
    z: int = Field(default=0, ge=0)
    text: str | None = Field(default=None, description="Первые знаки текста, если он есть")

    @property
    def bbox(self) -> BBox:
        return BBox(x=self.x, y=self.y, cx=self.cx, cy=self.cy)


class LayoutSpec(DomainModel):
    layout_id: str
    name: str
    master: str
    index: int = Field(ge=0, description="Позиция в slide_layouts исходного файла")
    kind: LayoutKind
    kind_confidence: float = Field(ge=0.0, le=1.0)
    kind_source: str = Field(description="heuristic | vlm | vlm+heuristic")
    capacity: LayoutCapacity
    placeholders: list[PlaceholderSpec]
    shapes: list[LayoutShape] = Field(
        default_factory=list,
        description="Фигуры вне плейсхолдеров: фон, фотографии, декор. Наполнению не подлежат.",
    )
    preview_png: str | None = None

    def placeholder(self, idx: int) -> PlaceholderSpec | None:
        return next((p for p in self.placeholders if p.idx == idx), None)


class DecorElement(DomainModel):
    layout_ids: list[str] = Field(default_factory=list)
    x: int
    y: int
    cx: int
    cy: int
    image_sha: str | None = None

    @property
    def bbox(self) -> BBox:
        return BBox(x=self.x, y=self.y, cx=self.cx, cy=self.cy)


class StaticShape(DomainModel):
    shape_id: str
    bbox: BBox
    z: int = 0


class FooterSpec(DomainModel):
    present: bool = False
    y_emu: int | None = None


class Decor(DomainModel):
    logo: DecorElement | None = None
    footer: FooterSpec = Field(default_factory=FooterSpec)
    static_shapes: list[StaticShape] = Field(default_factory=list)


class ChartDefaults(DomainModel):
    series_color_refs: list[ColorRef] = Field(default_factory=list)


class TemplateManifest(DomainModel):
    """Дизайн-система шаблона как самодостаточный кэшируемый JSON."""

    template_id: str = Field(description="sha256:<hex> исходного файла")
    source_name: str
    slide_size: SlideSize
    theme: Theme
    typography_scale: list[TypographyStep]
    grid: Grid
    layouts: list[LayoutSpec]
    decor: Decor = Field(default_factory=Decor)
    chart_defaults: ChartDefaults = Field(default_factory=ChartDefaults)
    parser_version: str

    @field_validator("layouts")
    @classmethod
    def _layouts_non_empty(cls, v: list[LayoutSpec]) -> list[LayoutSpec]:
        if not v:
            raise ValueError("манифест без макетов бесполезен для композиции")
        return v

    @model_validator(mode="after")
    def _unique_layout_ids(self) -> TemplateManifest:
        ids = [layout.layout_id for layout in self.layouts]
        if len(ids) != len(set(ids)):
            raise ValueError("layout_id должны быть уникальны в пределах манифеста")
        return self

    def layout(self, layout_id: str) -> LayoutSpec | None:
        return next((layout for layout in self.layouts if layout.layout_id == layout_id), None)

    def layouts_of_kind(self, kind: LayoutKind) -> list[LayoutSpec]:
        return [layout for layout in self.layouts if layout.kind == kind]

    def typography(self, role: TextRole) -> TypographyStep | None:
        return next((step for step in self.typography_scale if step.role == role), None)

    @property
    def size_ladder_pt(self) -> list[float]:
        """Разрешённые кегли по убыванию — единственный источник для авто-кегля."""
        return sorted({step.size_pt for step in self.typography_scale}, reverse=True)

    @property
    def content_bbox(self) -> BBox:
        m = self.grid.margins_emu
        return BBox(
            x=m.left,
            y=m.top,
            cx=self.slide_size.cx_emu - m.left - m.right,
            cy=self.slide_size.cy_emu - m.top - m.bottom,
        )
