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

    #: Фактическая гарнитура **этого** плейсхолдера, а не роли целиком.
    #: Нужна метрикам текста: считать ширину по гарнитуре темы, когда плейсхолдер набран
    #: другой, — значит полагаться на совпадение. На шаблонах кейса Arial и Play совпадают
    #: по ширине в пределах половины процента, но это удача, а не правило: на незнакомом
    #: шаблоне расхождение может быть любым (C6).
    font_family: str | None = None

    #: Кегль **этого** плейсхолдера. Общий кегль роли даёт заголовок 60 pt в полосе
    #: высотой 1,8 см — вписывание по такому кеглю не имеет смысла.
    size_pt: float | None = Field(default=None, gt=0)

    bold: bool | None = None

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


class LayoutBackground(DomainModel):
    """Фон макета: то, **по чему** на самом деле читается текст.

    Без этого поля проверка контраста сравнивала цвет текста со светлым слотом темы,
    то есть с догадкой. На тёмном макете догадка неверна: `dk1` по `dk1` — контраст
    1:1 — проходил как норма, и колода из двенадцати невидимых заголовков получала
    вердикт «нарушений нет».

    `color_hex` — всегда разрешённый цвет, по нему и считается контраст. `color_ref`
    заполнен тогда, когда фон задан слотом темы: смена шаблона перекрашивает его сама,
    и это важно знать тому, кто подбирает читаемый цвет текста (ADR-002).
    """

    color_hex: str = Field(pattern=HEX_COLOR)
    color_ref: ColorRef | None = Field(
        default=None, description="Слот темы, если фон задан ссылкой, а не литералом"
    )
    source: str = Field(
        description=(
            "Откуда взят фон: layout — из p:bg макета; master — унаследован от мастера; "
            "picture — усреднённый цвет подложки во весь слайд; theme — ни того, ни "
            "другого в шаблоне нет, взят светлый слот темы"
        )
    )
    is_image: bool = Field(
        default=False,
        description="Под текстом картинка: цвет усреднённый, вердикт по нему приблизителен",
    )


class LayoutSpec(DomainModel):
    layout_id: str
    name: str
    master: str

    #: Имя части макета в пакете, например `ppt/slideLayouts/slideLayout7.xml`.
    #: Единственный надёжный адрес макета: см. предупреждение у `index`.
    part_name: str

    index: int = Field(
        ge=0,
        description=(
            "Сквозной порядковый номер макета в манифесте. НЕ индекс в "
            "`prs.slide_layouts`: нумерация сквозная по всем мастерам, а макеты без "
            "пригодных плейсхолдеров пропускаются. Для адресации использовать `part_name`."
        ),
    )
    kind: LayoutKind
    kind_confidence: float = Field(ge=0.0, le=1.0)
    kind_source: str = Field(
        description=(
            "heuristic | heuristic+name | vlm | vlm+heuristic; "
            "+name — вид решило или подтвердило имя макета (Т8)"
        )
    )
    capacity: LayoutCapacity
    placeholders: list[PlaceholderSpec]
    shapes: list[LayoutShape] = Field(
        default_factory=list,
        description="Фигуры вне плейсхолдеров: фон, фотографии, декор. Наполнению не подлежат.",
    )
    background: LayoutBackground | None = Field(
        default=None,
        description=(
            "Фон макета. Пусто у манифестов, снятых до change (24): потребитель обязан "
            "это различать, а не подставлять светлый фон молча"
        ),
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


class BulletStyle(DomainModel):
    """Маркер списка первого уровня — часть дизайн-системы шаблона, а не наш вкус.

    Свободный текстбокс в OOXML не наследует ни знака, ни отступа: родителя-плейсхолдера
    у него нет. Без этих сведений список выглядит набором абзацев (прогон 2ac85990b2f2).
    Шаблон, который маркера не задаёт, остаётся без маркера: дорисовывать «типовую точку»
    значит придумывать чужой дизайн.
    """

    char: str = Field(min_length=1, max_length=4, description="Знак маркера из buChar")
    font: str | None = Field(default=None, description="Гарнитура знака из buFont")
    color_ref: ColorRef | None = Field(default=None, description="Цвет — слотом темы (ADR-002)")
    margin_left_emu: int = Field(default=0, ge=0, description="marL: отступ абзаца")
    indent_emu: int = Field(default=0, le=0, description="indent: вынос маркера, ≤ 0")


class ChartDefaults(DomainModel):
    series_color_refs: list[ColorRef] = Field(default_factory=list)


class ExampleShape(DomainModel):
    """Одна фигура слайда-примера, приведённая к координатам слайда.

    Примеры — это то, что автор шаблона нарисовал сам: у трёх шаблонов кейса от 87 %
    до 96 % их содержимого лежит **вне** плейсхолдеров, обычными фигурами поверх почти
    пустого макета. Поэтому у примера важна не «вместимость», а геометрия, тип и набор:
    по ним видно, каким автор считает слайд этого макета.

    Фигуры внутри групп раскрыты, а их геометрия и кегль пересчитаны с учётом масштаба
    группы: у VK Tech иначе кегли 6,75 и 8,12 pt выглядят ступенями шкалы, хотя это
    масштаб группы, а не решение о типографике.
    """

    shape_id: str
    kind: ShapeKind
    x: int
    y: int
    cx: int = Field(gt=0)
    cy: int = Field(gt=0)
    z: int = Field(default=0, ge=0)
    xml_id: int | None = Field(
        default=None,
        description=(
            "Настоящий cNvPr id фигуры в XML; по нему фигура находится "
            "при копировании рецепта"
        ),
    )
    placeholder_idx: int | None = Field(
        default=None,
        description="idx плейсхолдера макета, если фигура стоит в нём; иначе свободная фигура",
    )
    role: TextRole | None = Field(
        default=None, description="Роль текста, если её удалось определить по кеглю и месту"
    )
    text_len: int = Field(default=0, ge=0, description="Длина текста фигуры в знаках")
    size_pt: float | None = Field(
        default=None, gt=0, description="Кегль, приведённый к масштабу слайда"
    )
    #: Кегль, который задаёт этому плейсхолдеру макет. Тоже число автора, но в разборе
    #: не участвует: `size_pt` выбирает ступень и считает вместимость, и подмешивать
    #: туда кегль макета нельзя — сдвинется весь каталог. Нужен писателю, чтобы опустить
    #: кегль там, где вписывание этого потребовало (D04, RG42).
    layout_size_pt: float | None = Field(default=None, gt=0)
    font_family: str | None = Field(
        default=None, description="Гарнитура; ссылки +mj-lt/+mn-lt разрешены через тему"
    )
    color_ref: ColorRef | None = Field(default=None, description="Цвет текста слотом темы")
    color_hex: str | None = Field(
        default=None,
        pattern=HEX_COLOR,
        description="Литеральный цвет текста, когда он не сводится к слоту темы",
    )
    fill_ref: ColorRef | None = Field(default=None, description="Заливка фигуры слотом темы")
    fill_hex: str | None = Field(
        default=None,
        pattern=HEX_COLOR,
        description="Литеральная заливка фигуры: из неё складывается палитра шаблона",
    )

    @property
    def bbox(self) -> BBox:
        return BBox(x=self.x, y=self.y, cx=self.cx, cy=self.cy)


class TemplateExample(DomainModel):
    """Слайд-пример шаблона: что автор поставил на этот макет.

    `layout_id` пуст, когда слайд ссылается на макет, которого нет в манифесте
    (у макета не оказалось пригодных плейсхолдеров, и парсер его не взял). Такой пример
    остаётся в списке: его фигуры всё равно говорят о дизайн-системе.
    """

    slide_index: int = Field(ge=1, description="Номер части ppt/slides/slideN.xml")
    part_name: str | None = Field(
        default=None,
        description=(
            "Имя части слайда-примера (slideN.xml); по нему часть находится "
            "при копировании рецепта"
        ),
    )
    layout_id: str | None = None
    shapes: list[ExampleShape] = Field(default_factory=list)


class FontUsage(DomainModel):
    """Сколько знаков в шаблоне набрано этой гарнитурой.

    Тема называет гарнитуру, которой шаблон не пользуется: у всех трёх шаблонов кейса
    в теме Arial, а примеры набраны Play. Аудит, сверяющий шрифт колоды с темой, на этом
    даёт ложные находки (C3, C10).
    """

    family: str = Field(min_length=1)
    chars: int = Field(ge=0)
    share: float = Field(ge=0.0, le=1.0, description="Доля знаков шаблона")
    in_titles: bool = Field(default=False, description="Встречается в ролях заголовка")
    in_body: bool = Field(default=False, description="Встречается в основном тексте")


class PaletteColor(DomainModel):
    """Литеральный цвет, которым шаблон пользуется помимо двенадцати слотов темы.

    Цвет остаётся описанием шаблона: в `SlideIR` он не попадает — правило 5 требует
    имя слота темы. Палитра нужна аудиту и профилю метрик, а рендереру — не раньше DS4.
    """

    color_hex: str = Field(pattern=HEX_COLOR)
    count: int = Field(ge=1, description="Сколько раз встретился")
    nearest_ref: ColorRef = Field(description="Ближайший слот темы")
    delta_e: float = Field(ge=0.0, description="Расстояние до ближайшего слота")


class TemplateUsage(DomainModel):
    """Чем шаблон пользуется на самом деле, в отличие от того, что объявляет тема."""

    fonts: list[FontUsage] = Field(default_factory=list)
    palette: list[PaletteColor] = Field(default_factory=list)

    def knows_font(self, family: str) -> bool:
        """Набран ли шаблон этой гарнитурой. Сверка без учёта регистра и пробелов."""
        needle = family.strip().casefold()
        return any(usage.family.strip().casefold() == needle for usage in self.fonts)


class ComponentKind(StrEnum):
    """Вид повторяющегося элемента шаблона.

    Список короткий нарочно: это те виды, которые наш рендерер умеет рисовать сам
    (`kpi`, `smartart`, плитки). Вид, который мы не рисуем, в каталоге бесполезен —
    описать его есть чем, а воспользоваться нечем.
    """

    TILE = "tile"
    PICTURE_CAPTION = "picture_caption"
    KPI = "kpi"


class ComponentSpec(DomainModel):
    """Повторяющийся элемент, который автор шаблона нарисовал сам. Задача DS3.

    Каталог собирается из слайдов-примеров: элемент, повторённый на одном слайде три
    раза и больше с равным шагом, — это не случайность, а компонент дизайн-системы.
    У VK WorkSpace так устроена «картинка + подпись», у VK Education — карточка.

    Хранятся **параметры**, а не куски XML. Скопированный фрагмент принёс бы с собой
    литеральные цвета (19 штук у VK Tech), а правило 5 требует ссылку на слот темы.
    По этим параметрам рисует наш рендерер (DS4), и тогда плитки и показатели
    получаются в пропорциях шаблона, а не в наших.
    """

    kind: ComponentKind
    repeats: int = Field(ge=3, description="Сколько экземпляров стояло рядом")
    axis: str = Field(description="row — экземпляры в ряд, column — столбцом")
    width_share: float = Field(gt=0, le=1, description="Ширина экземпляра в долях слайда")
    height_share: float = Field(gt=0, le=1, description="Высота экземпляра в долях слайда")
    gap_share: float = Field(
        ge=0, le=1, description="Шаг между экземплярами в долях стороны вдоль оси"
    )
    parts: list[ShapeKind] = Field(
        default_factory=list, description="Из чего состоит экземпляр, по одному разу на вид"
    )
    text_sizes_pt: list[float] = Field(
        default_factory=list, description="Кегли текстов экземпляра по убыванию"
    )
    fill_ref: ColorRef | None = Field(default=None, description="Заливка экземпляра слотом темы")
    fill_hex: str | None = Field(default=None, pattern=HEX_COLOR)
    seen_on: list[int] = Field(
        default_factory=list, description="Номера слайдов-примеров, где элемент встречен"
    )

    @property
    def aspect(self) -> float:
        """Пропорции экземпляра: по ним рендерер и строит плитку."""
        return self.width_share / self.height_share if self.height_share else 0.0


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
    bullet_levels: list[BulletStyle] = Field(
        default_factory=list,
        description="Маркеры списка по уровням, начиная с первого. Пусто — шаблон их не задаёт",
    )
    chart_defaults: ChartDefaults = Field(default_factory=ChartDefaults)
    examples: list[TemplateExample] = Field(
        default_factory=list,
        description="Слайды-примеры шаблона. Пусто — в шаблоне нет ни одного слайда",
    )
    usage: TemplateUsage = Field(
        default_factory=TemplateUsage,
        description="Гарнитуры и цвета по фактическому набору, а не по объявлению темы",
    )
    components: list[ComponentSpec] = Field(
        default_factory=list,
        description="Каталог повторяющихся элементов шаблона. Пусто — примеров нет",
    )
    extra_themes: list[Theme] = Field(
        default_factory=list,
        description="Темы прочих мастеров: колоду задаёт первая, остальные нужны аудиту",
    )
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

    @property
    def bullet(self) -> BulletStyle | None:
        """Маркер первого уровня — самый частый случай: список без вложенности."""
        return self.bullet_levels[0] if self.bullet_levels else None

    def bullet_for(self, level: int) -> BulletStyle | None:
        """Маркер для уровня пункта.

        Уровень, которого в шаблоне нет, наследует ближайший объявленный сверху —
        так же поступает и PowerPoint, когда уровень не описан в `txStyles`.
        """
        if not self.bullet_levels:
            return None
        return self.bullet_levels[min(max(level, 0), len(self.bullet_levels) - 1)]

    def layout(self, layout_id: str) -> LayoutSpec | None:
        return next((layout for layout in self.layouts if layout.layout_id == layout_id), None)

    def layouts_of_kind(self, kind: LayoutKind) -> list[LayoutSpec]:
        return [layout for layout in self.layouts if layout.kind == kind]

    def component(self, kind: ComponentKind) -> ComponentSpec | None:
        """Самый частый компонент этого вида. Нет такого — рисуем как рисовали."""
        matching = [item for item in self.components if item.kind is kind]
        return max(matching, key=lambda item: len(item.seen_on), default=None)

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
