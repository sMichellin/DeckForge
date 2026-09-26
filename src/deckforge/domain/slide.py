"""`SlideIR` — выход композиции, единственный вход рендерера (ARCHITECTURE.md §4.4).

LLM производит **только** эту структуру. Она валидируется до того, как будет создан файл (ADR-001).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from deckforge.domain.base import BBox, DomainModel
from deckforge.domain.enums import (
    CalloutTone,
    ChartType,
    ColorRef,
    ImageFit,
    ImageSource,
    ListStyle,
    SmartArtPattern,
    TextRole,
)


class _Positioned(DomainModel):
    """Координаты в EMU. Если не заданы — берутся из плейсхолдера макета."""

    x: int | None = Field(default=None, ge=0)
    y: int | None = Field(default=None, ge=0)
    cx: int | None = Field(default=None, gt=0)
    cy: int | None = Field(default=None, gt=0)
    zone_id: str | None = Field(
        default=None,
        description=(
            "Зона рецепта, в которую пишется блок (slide-recipes); не задан — "
            "блок идёт в плейсхолдер макета"
        ),
    )

    @property
    def bbox(self) -> BBox | None:
        if None in (self.x, self.y, self.cx, self.cy):
            return None
        return BBox(x=self.x, y=self.y, cx=self.cx, cy=self.cy)

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


#: Имя иконки набора проекта (Lucide, `assets/icons/`): слова латиницей через дефис.
#: Форма имени, а не список: набор живёт в слое рендера, домен файлов не читает. Путь,
#: расширение и цвет (`#RRGGBB`) этой формой отвергаются; неизвестное имя снимает рендер.
ICON_NAME = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class BulletItem(DomainModel):
    text: str
    level: int = Field(default=0, ge=0, le=4)
    #: Новое поле идёт последним и необязательно: старые колоды и чекпойнты валидны.
    icon: str | None = Field(
        default=None,
        pattern=ICON_NAME,
        description="Иконка пункта иконочного списка: имя Lucide (shield-check), не путь и не цвет",
    )


class BulletsBlock(_Positioned):
    block_id: str
    type: Literal["bullets"] = "bullets"
    placeholder_idx: int | None = Field(default=None, ge=0)
    role: TextRole = TextRole.BODY
    items: list[BulletItem] = Field(min_length=1)
    max_level: int = Field(default=1, ge=0, le=4)
    size_pt: float | None = Field(default=None, gt=0)
    #: Новое поле идёт последним и необязательно: старые колоды и чекпойнты валидны.
    style: ListStyle | None = Field(
        default=None,
        description=(
            "Стиль списка: bulleted, numbered или icon; не задан — маркированный. "
            "Знак, цвет и отступ рисует вёрстка по дизайн-системе шаблона"
        ),
    )


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


class QuoteBlock(_Positioned):
    """Цитата с акцентной полосой (DG4, страница дизайн-системы #142).

    Модель задаёт только содержание и слот цвета. Ширину полосы, отбивку и кегль
    решает вёрстка по дизайн-системе шаблона: кегля здесь нет (правило 6).
    """

    block_id: str
    type: Literal["quote"] = "quote"
    text: str = Field(min_length=1)
    author: str | None = None
    accent_ref: ColorRef | None = Field(
        default=None,
        description="Слот темы для полосы; не задан — акцент берёт вёрстка по дизайн-системе",
    )


class CalloutBlock(_Positioned):
    """Callout «инсайт» или «риск» (DG4, страница дизайн-системы #142).

    `tone` — закрытое перечисление: вид callout входит в контракт. Плашку, подпись вида
    и отступы рисует вёрстка; кегля здесь нет (правило 6).
    """

    block_id: str
    type: Literal["callout"] = "callout"
    text: str = Field(min_length=1)
    tone: CalloutTone
    accent_ref: ColorRef | None = Field(
        default=None,
        description="Слот темы для акцента; не задан — акцент берёт вёрстка по дизайн-системе",
    )


Block = Annotated[
    TextBlock
    | BulletsBlock
    | ChartBlock
    | TableBlock
    | SmartArtBlock
    | IconBlock
    | ImageBlock
    | KpiBlock
    | QuoteBlock
    | CalloutBlock,
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
    strategy: str | None = Field(
        default=None,
        description="as_is | shrink | grow | shorten | split | below_reading; "
        "below_reading — кегль под порогом читаемости: зона уже одного слова "
        "на пороге, и текст оставлен вместо снятия (D06, RG35)",
    )


class SlideIR(DomainModel):
    slide_id: str
    layout_id: str
    variant: str = Field(pattern=r"^[A-Z]$")
    blocks: list[Block]
    speaker_note: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)
    fit_report: dict[str, FitResult] = Field(default_factory=dict)
    recipe_id: str | None = Field(
        default=None,
        description=(
            "Рецепт (слайд-пример шаблона), по которому writer копирует слайд "
            "(slide-recipes)"
        ),
    )

    @model_validator(mode="after")
    def _unique_block_ids(self) -> SlideIR:
        ids = [b.block_id for b in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("block_id должны быть уникальны в пределах слайда")
        return self

    def block(self, block_id: str) -> Block | None:
        return next((b for b in self.blocks if b.block_id == block_id), None)

    @property
    def by_recipe(self) -> bool:
        """Слайд собран по рецепту: рецепт назван И каждый блок стоит в зоне шаблона.

        Один предикат на весь конвейер (change `by-recipe-is-one-predicate`). До него
        «слайд по рецепту» понимали тремя разными способами — вписывание по непустому
        `recipe_id`, проверка писателя по паре «`recipe_id` и `zone_id` блока», сам
        писатель по наличию рецепта в каталоге, — и расхождение этих трёх условий
        положило пять прогонов 24.09: вписывание слайд пропускало, проверка молчала,
        а писатель брал кегль из пустого `fit_report`.

        Спрашивается именно форма слайда, а не существование рецепта: каталог композиций
        — это дизайн-система шаблона, а `domain` о ней ничего не знает и знать не должен
        (ADR-003). «Есть ли такой рецепт в каталоге» — отдельный вопрос, и задавать его
        может только тот, у кого каталог на руках, то есть писатель.

        Рамки у такого слайда от автора шаблона, поэтому ни координат, ни плейсхолдера,
        ни отчёта о вписывании у его блоков нет и быть не должно. Смешанный слайд —
        часть блоков в зонах, часть нет — по рецепту не собран: вписать его по макету
        нельзя (блоку в зоне нечего мерить), а скопировать пример целиком тоже нельзя
        (блоку вне зоны некуда встать). Такой слайд назовёт проверка перед записью.
        """
        return bool(self.recipe_id) and bool(self.blocks) and all(
            block.zone_id is not None for block in self.blocks
        )


class DeckIR(DomainModel):
    """Колода целиком: то, что уходит в рендерер и экспорт."""

    deck_id: str
    variant: str = Field(pattern=r"^[A-Z]$")
    template_id: str
    language: str = "ru"
    seed: int
    slides: list[SlideIR]
