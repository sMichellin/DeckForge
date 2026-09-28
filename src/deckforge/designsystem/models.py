"""Структура `DesignSystem` — дизайн-система шаблона, разобранная по разделам страницы.

Одна структура, а не семь: разделам соответствуют её поля, и у каждого поля есть признак
происхождения `Origin`. Из него рендер ставит метку «измерено в шаблоне» / «достроено
системой», и метку не приходится проставлять руками в каждом блоке — иначе она разойдётся
с правдой на первом же бедном шаблоне.

Модели домена (`deckforge.domain`) здесь не расширяются и не правятся: производные —
не часть контракта `TemplateManifest` и в `schemas/` не едут (правило 11).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from deckforge.domain.base import DomainModel
from deckforge.domain.enums import ColorRef, FontRef, TextRole
from deckforge.domain.template import HEX_COLOR, ComponentKind, Margins


class Origin(StrEnum):
    """Откуда взялось содержимое блока.

    Перечисление, а не булево `is_derived`: булево читается наоборот ровно в половине
    мест, где его пишут, и метка на странице оказывается перевёрнутой.
    """

    MEASURED = "measured"
    DERIVED = "derived"


class TypeLevel(StrEnum):
    """Ступень типографической лестницы страницы — восемь уровней из образца заказчика.

    Не то же самое, что `TextRole`: ролей в домене четыре, и они описывают контракт
    композиции (что писать в заголовок, что в подпись). Уровень описывает лестницу,
    которую человек видит на странице: между заголовком слайда и основным текстом
    живут заголовок карточки и крупный абзац, а под подписью — метка.

    Порядок объявления — порядок лестницы, сверху вниз.
    """

    DISPLAY = "display"
    SLIDE_TITLE = "slide_title"
    SECTION_SUBTITLE = "section_subtitle"
    CARD_TITLE = "card_title"
    BODY_LARGE = "body_large"
    BODY = "body"
    CAPTION = "caption"
    LABEL = "label"


class TypeStep(DomainModel):
    """Ступень лестницы типографики: роль шаблона, названная словами и в долях слайда."""

    role: TextRole
    size_pt: float = Field(gt=0)
    font_family: str = Field(min_length=1, description="Гарнитура темы, разрешённая по font_ref")
    font_ref: FontRef
    bold: bool = False
    italic: bool = False
    line_spacing: float | None = Field(default=None, gt=0)
    color_ref: ColorRef
    purpose: str = Field(min_length=1, description="Назначение роли словами")
    width_share: float = Field(
        gt=0,
        description=(
            "Кегль в долях ширины слайда: по нему страница рисует пример в пропорции "
            "шаблона, а не в пикселях из головы"
        ),
    )
    origin: Origin = Origin.MEASURED
    #: Новое поле идёт последним: форму `TypeStep` читают параллельные таски, и порядок
    #: объявленных до него полей менять нельзя.
    level: TypeLevel = Field(
        description=(
            "Ступень лестницы страницы. Уровень, которого в шкале шаблона нет, "
            "достроен из её же ступеней и несёт origin=derived"
        )
    )


class Typography(DomainModel):
    steps: list[TypeStep] = Field(default_factory=list)
    origin: Origin = Origin.DERIVED


class SpacingScale(DomainModel):
    """Шкала отступов: базовый шаг шаблона и его кратности.

    Шагом меряются отступы, радиусы и толщины достроенных элементов, поэтому он обязан
    быть ненулевым на любом шаблоне — отсюда три источника подряд, от объявленного
    к выведенному.
    """

    base_emu: int = Field(gt=0)
    #: Значения перечислены как «имя — пояснение» через точку с запятой: по этому
    #: описанию таск 04 узнаёт набор, не читая `derive`. Набор обязан совпадать с тем,
    #: что отдаёт `_base_step`, — расхождение проверяется тестом.
    base_source: str = Field(
        description=(
            "gutter — шаг объявлен в сетке; margins_gcd — НОД полей; "
            "margin — наименьшее поле; columns — ширина колонки"
        )
    )
    steps_emu: list[int] = Field(default_factory=list, description="Кратности базового шага")
    steps_in_margin: int = Field(
        ge=0, description="Сколько базовых шагов укладывается в наименьшее ненулевое поле"
    )
    origin: Origin = Origin.MEASURED


class GridSpec(DomainModel):
    """Формат, поля, колонки и шкала отступов — раздел «Сетка и модуль слайда»."""

    width_emu: int = Field(gt=0)
    height_emu: int = Field(gt=0)
    aspect: str
    margins: Margins
    columns: int = Field(gt=0)
    gutter_emu: int = Field(ge=0)
    column_width_emu: int = Field(gt=0)
    content_width_emu: int = Field(gt=0)
    content_height_emu: int = Field(gt=0)
    spacing: SpacingScale
    #: Метка всего блока: формат, пропорции и размеры слайда сняты из `slide_size`
    #: и измерены на любом шаблоне. Одна метка `derived` на весь раздел объявила бы
    #: достроенным и формат — а его никто не выводил.
    origin: Origin = Origin.MEASURED
    #: Новое поле идёт последним: форму `GridSpec` читают параллельные таски.
    guides_origin: Origin = Field(
        default=Origin.MEASURED,
        description=(
            "Поля, колонки и шаг: measured — направляющие объявлены в мастере, "
            "derived — выведены кластеризацией"
        ),
    )


class BulletSpec(DomainModel):
    """Маркер списка первого уровня. Пустой знак — шаблон маркера не задаёт."""

    char: str | None = None
    font: str | None = None
    color_ref: ColorRef | None = None
    margin_left_emu: int = Field(default=0, ge=0)
    indent_emu: int = Field(default=0, le=0)
    origin: Origin = Origin.DERIVED


class ThemeSlot(DomainModel):
    """Слот темы и его цвет. Литеральные цвета структуры живут только здесь."""

    ref: ColorRef
    name: str = Field(min_length=1, description="Имя слота: им же называется CSS-переменная")
    color_hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class ThemeInfo(DomainModel):
    slots: list[ThemeSlot] = Field(default_factory=list)
    major_font: str = ""
    minor_font: str = ""
    origin: Origin = Origin.MEASURED


# --- измеренное по слайдам-примерам (таск 02) ---------------------------------


class ColorRoleKind(StrEnum):
    """Роль цвета в шаблоне. Выводится из доли площади, а не из частоты появления."""

    BACKGROUND = "background"
    DOMINANT = "dominant"
    ACCENT = "accent"
    RARE = "rare"
    TAIL = "tail"


class PaletteRole(DomainModel):
    """Цвет шаблона с его ролью и долей площади.

    `count` и `label` заполнены только у хвоста: девятнадцать литералов одного шаблона
    сворачиваются в одну запись «ещё N оттенков», иначе раздел превращается в простыню.
    """

    role: ColorRoleKind
    color_hex: str = Field(pattern=HEX_COLOR)
    nearest_ref: ColorRef | None = Field(default=None, description="Ближайший слот темы")
    share: float = Field(ge=0.0, le=1.0, description="Доля площади слайдов-примеров")
    seen_on: list[int] = Field(default_factory=list, description="Номера слайдов-примеров")
    count: int = Field(default=1, ge=0, description="Сколько цветов сведено в запись")
    label: str = Field(default="", description="Подпись записи-хвоста")
    origin: Origin = Origin.MEASURED


class Combination(DomainModel):
    """Тройка «фон + текст + акцент», которая действительно встречалась на примерах.

    Сценарий словами не называется: это была бы интерпретация. Называются доля
    и номера слайдов.
    """

    background_hex: str = Field(pattern=HEX_COLOR)
    text_hex: str | None = Field(default=None, pattern=HEX_COLOR)
    accent_hex: str | None = Field(default=None, pattern=HEX_COLOR)
    share: float = Field(ge=0.0, le=1.0, description="Доля слайдов-примеров")
    seen_on: list[int] = Field(default_factory=list)
    origin: Origin = Origin.MEASURED


class ContrastLevel(StrEnum):
    AA = "aa"
    AA_LARGE = "aa_large"
    FAIL = "fail"


class ContrastPair(DomainModel):
    """Пара «текст на фоне» с коэффициентом. Считается `domain.rules`, своей формулы нет."""

    foreground_hex: str = Field(pattern=HEX_COLOR)
    background_hex: str = Field(pattern=HEX_COLOR)
    foreground_label: str = Field(default="", description="Слот темы или роль цвета словами")
    background_label: str = Field(default="")
    ratio: float = Field(ge=0.0)
    level: ContrastLevel
    from_theme: bool = Field(default=False, description="Пара собрана из слотов темы")
    is_risk: bool = Field(
        default=False, description="Шаблон сам себе противоречит: пара из темы не проходит AA"
    )
    display_only: bool = Field(
        default=False, description="Годен для графики и крупных меток, не для абзаца"
    )
    #: Change `a-minimum-is-not-a-norm`: порог зависит от роли текста, а «прошло впритык»
    #: перестаёт выглядеть как «прошло».
    required: float = Field(
        default=4.5, gt=0, description="Порог, который этой паре нужно было взять"
    )
    comfort: float = Field(
        default=4.5, gt=0, description="Порог с запасом: ниже него подпись не ставят"
    )
    tight: bool = Field(
        default=False, description="Минимум взят, запаса нет — для мелкого текста не годится"
    )
    approximate: bool = Field(
        default=False, description="Фон картинкой: цвет усреднён, оценка приблизительна"
    )
    origin: Origin = Origin.MEASURED


class ContrastDefect(DomainModel):
    """Место, где шаблон не даёт читаемой пары ни одним слотом своей темы.

    Дефект называется на разборе шаблона, а не всплывает на готовой презентации:
    в этом весь смысл разбора.
    """

    where: str = Field(min_length=1, description="Что именно нечитаемо, словами")
    text_class: str = Field(min_length=1, description="Класс текста: крупный, основной, подпись")
    background_label: str = Field(default="", description="Фон, на котором это стоит")
    background_hex: str = Field(pattern=HEX_COLOR)
    required: float = Field(gt=0, description="Сколько требовалось")
    best_ratio: float = Field(ge=0, description="Лучшее, что даёт тема на этом фоне")
    best_ref: ColorRef | None = Field(
        default=None, description="Слот, давший этот лучший результат"
    )
    origin: Origin = Origin.MEASURED


class FontInUse(DomainModel):
    """Гарнитура по фактическому набору — отдельно от объявленной в теме."""

    family: str = Field(min_length=1)
    share: float = Field(ge=0.0, le=1.0, description="Доля знаков шаблона")
    in_titles: bool = False
    in_body: bool = False
    origin: Origin = Origin.MEASURED


class NumberScale(DomainModel):
    """Три размера числа: крупный из KPI-компонента, остальные — вниз по шкале шаблона."""

    large_pt: float | None = Field(default=None, gt=0)
    medium_pt: float | None = Field(default=None, gt=0)
    small_pt: float | None = Field(default=None, gt=0)
    origin: Origin = Origin.DERIVED


class ComponentCard(DomainModel):
    """Повторяющийся элемент шаблона в пропорциях слайда — карточка раздела «Элементы»."""

    kind: ComponentKind
    repeats: int = Field(ge=0)
    axis: str = ""
    width_share: float = Field(ge=0.0, le=1.0)
    height_share: float = Field(ge=0.0, le=1.0)
    gap_share: float = Field(default=0.0, ge=0.0, le=1.0)
    text_sizes_pt: list[float] = Field(default_factory=list)
    fill_ref: ColorRef | None = None
    fill_hex: str | None = Field(default=None, pattern=HEX_COLOR)
    seen_on: list[int] = Field(default_factory=list)
    origin: Origin = Origin.MEASURED


# --- достроенное из примитивов шаблона (таск 03) ------------------------------


class SynthElement(DomainModel):
    """Элемент, достроенный из примитивов шаблона: цвет слотом, кегль из шкалы,
    размеры — долями базового шага. Ни одного числа «из головы».

    `group` собирает элементы в раздел страницы, `kind` различает их внутри раздела.
    Размеры необязательны: у метки есть кегль, у разделителя — толщина, у бейджа — радиус.
    """

    group: str = Field(min_length=1, description="Раздел страницы: плашки, списки, элементы")
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    purpose: str = Field(default="", description="Для чего элемент нужен, словами")
    text: str = Field(default="", description="Образец текста или знак маркера")
    shown_ref: ColorRef | None = Field(
        default=None,
        description=(
            "Слот, которым знак нарисован, если объявленный не берёт свой порог. "
            "Объявление шаблона при этом остаётся в `color_ref` (a-minimum-is-not-a-norm)"
        ),
    )
    plate_ref: ColorRef | None = Field(
        default=None,
        description=(
            "Слот, которым залита плашка, если объявленный не даёт читаемой надписи: "
            "тот же цвет глубже (a-minimum-is-not-a-norm)"
        ),
    )
    outlined: bool = Field(
        default=False,
        description=(
            "Акцент оставлен границей, а не заливкой: подписи на этой заливке не хватает "
            "запаса контраста (a-minimum-is-not-a-norm)"
        ),
    )
    note: str = Field(
        default="",
        description="Оговорка слоя: почему нарисовано не объявленным слотом",
    )
    color_ref: ColorRef | None = None
    on_color_ref: ColorRef | None = Field(default=None, description="Слот фона под элементом")
    size_pt: float | None = Field(default=None, gt=0)
    spacing_emu: int | None = Field(default=None, ge=0)
    radius_emu: int | None = Field(default=None, ge=0)
    line_emu: int | None = Field(default=None, ge=0)
    origin: Origin = Origin.DERIVED


class AssemblyRule(DomainModel):
    """Правило сборки. Правило без числа из шаблона на страницу не попадает: это был бы
    чужой совет, выданный за анализ."""

    text: str = Field(min_length=1)
    value: float
    unit: str = Field(default="", description="emu | pt | шт | строк")
    source: str = Field(min_length=1, description="Откуда число: поле манифеста")
    origin: Origin = Origin.DERIVED


# --- каталог композиций шаблона (change `recipes-in-the-design-system`) --------


class RecipeKind(StrEnum):
    """Вид композиции. Выводится из фигур примера, а не из имени его макета."""

    COVER = "cover"
    SECTION = "section"
    FINAL = "final"
    METRICS = "metrics"
    CARDS = "cards"
    TEXT_WITH_PICTURE = "text_with_picture"
    TEXT = "text"


class Zone(DomainModel):
    """Текстовая фигура рецепта, которую заполняет наш текст.

    `xml_id` — настоящий `cNvPr id` фигуры в файле: по нему writer найдёт её при
    копировании. Текста примера здесь нет и не будет: рецепту нужен размер зоны
    и её кегль, а не чужие слова.

    Рамка (`x`, `y`, `cx`, `cy`) — фигуры примера в координатах слайда, с учётом масштаба
    группы (change `zone-carries-its-frame`, RG18). Писателю pptx она не нужна — он
    копирует фигуру целиком; нужна тем, кто верстает слайд по рецепту без файла шаблона:
    html ставит блок туда же, куда его поставит PowerPoint. Не `BBox`: фигура примера
    бывает заведена за край слайда, и `x`, `y` у неё отрицательные.
    """

    zone_id: str = Field(min_length=1)
    xml_id: int | None = Field(default=None, description="cNvPr id фигуры в файле шаблона")
    role: TypeLevel
    repeat: int | None = Field(default=None, description="Номер повтора, если зона внутри него")
    capacity_chars: int = Field(ge=0, description="Сколько знаков держит рамка при своём кегле")
    size_pt: float | None = Field(default=None, gt=0)
    #: Новые поля идут последними и необязательны: дизайн-система лежит в чекпойнте,
    #: и ДС, сохранённая до этого change, обязана читаться без правок.
    #: Кегль, который **стоит у автора**: свой у фигуры примера или заданный ей макетом.
    #: Отличается от `size_pt` тем, что никогда не бывает подстановкой ступени лестницы.
    #: Нужен писателю: подставленное число ставить в файл нельзя — им роняли VK Tech s03
    #: с 16 до 7,8 pt и поднимали VK Education s04/s11 с 36 до 39 (D04, RG42).
    author_size_pt: float | None = Field(default=None, gt=0)
    x: int | None = Field(default=None, description="Левый край рамки зоны, EMU от края слайда")
    y: int | None = Field(default=None, description="Верхний край рамки зоны, EMU от края слайда")
    cx: int | None = Field(default=None, gt=0, description="Ширина рамки зоны, EMU")
    cy: int | None = Field(default=None, gt=0, description="Высота рамки зоны, EMU")

    @property
    def has_frame(self) -> bool:
        """Рамка известна целиком: зона из каталога до этого change её не несёт."""
        return None not in (self.x, self.y, self.cx, self.cy)


# --- паспорт примера (план Б, change `the-example-passport-model`, ADR-009) ---------


class PlaceKind(StrEnum):
    """Что держит место примера. Решает, чем его заполняет композиция."""

    TEXT = "text"
    NUMBER = "number"
    PICTURE = "picture"


class Place(DomainModel):
    """Одно место примера, которое заполняет наша колода.

    Текстовое место ссылается на зону рецепта (`zone_id`): рамка, кегль и адрес фигуры
    живут там, а не дублируются. Картинка зоны не имеет — у неё только адрес фигуры.

    `capacity_chars` — ёмкость по метрикам шрифта примера (план Б, шаг 1), а не
    `Zone.capacity_chars` = 0,52 × кегль на знак: паспорт и вписывание обязаны мерить
    одним способом, иначе текст, написанный «ровно под место», в место не встанет.
    """

    place_id: str = Field(pattern=r"^p\d{2,}$")
    kind: PlaceKind
    zone_id: str | None = Field(default=None, description="Зона рецепта; у картинки — нет")
    xml_id: int | None = Field(default=None, description="cNvPr id фигуры в файле шаблона")
    role: TypeLevel | None = Field(default=None, description="Ступень лестницы; у картинки — нет")
    capacity_chars: int = Field(default=0, ge=0, description="Знаков по метрикам шрифта")

    @model_validator(mode="after")
    def _kind_matches_fields(self) -> Place:
        if self.kind is PlaceKind.PICTURE:
            if self.zone_id is not None or self.role is not None:
                raise ValueError(f"{self.place_id}: у картинки нет зоны и ступени лестницы")
            return self
        if self.zone_id is None or self.role is None:
            raise ValueError(f"{self.place_id}: текстовому месту нужны зона и ступень")
        if self.capacity_chars == 0:
            raise ValueError(f"{self.place_id}: текстовое место без ёмкости не заполнить")
        return self

    @property
    def shape(self) -> tuple[PlaceKind, TypeLevel | None]:
        """Что за место, без размеров: по нему сверяются повторы одного ряда."""
        return self.kind, self.role


class PlaceGroup(DomainModel):
    """Места, которые живут и уходят вместе: карточка, пункт схемы, одиночный заголовок.

    `decor_xml_ids` — фигуры группы без нашего текста: плашка, иконка, линии. Незаполненная
    группа удаляется с ними целиком (план Б, шаг 4), а не угадыванием по координатам.

    `row` — ряд взаимозаменяемых групп (карточки в сетке). Группы одного ряда обязаны
    иметь одну форму: тогда композиция пишет «N × (подзаголовок, текст)», а вёрстка
    убирает лишние повторы с конца ряда.
    """

    group_id: str = Field(pattern=r"^g\d{2,}$")
    places: list[Place] = Field(min_length=1)
    decor_xml_ids: list[int] = Field(default_factory=list)
    row: str | None = Field(default=None, description="Ряд повторов; None — одиночная группа")
    x: int | None = Field(default=None, description="Левый край рамки группы, EMU")
    y: int | None = Field(default=None, description="Верхний край рамки группы, EMU")
    cx: int | None = Field(default=None, gt=0, description="Ширина рамки группы, EMU")
    cy: int | None = Field(default=None, gt=0, description="Высота рамки группы, EMU")

    @property
    def shape(self) -> tuple[tuple[PlaceKind, TypeLevel | None], ...]:
        return tuple(place.shape for place in self.places)


class ExamplePassport(DomainModel):
    """Паспорт слайда-примера: его места, собранные в группы (план Б, шаг 1).

    Контракт между потоками A и B (`docs/agents/tasks-plan-b.md`, change 1а): композиция
    пишет текст под места паспорта, вёрстка удаляет и перестраивает группы паспорта.
    Строит паспорт change `the-example-passport`; здесь — только форма и её инварианты.
    """

    groups: list[PlaceGroup] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_and_rows_are_consistent(self) -> ExamplePassport:
        group_ids = [group.group_id for group in self.groups]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError(f"группы паспорта повторяются: {sorted(group_ids)}")
        place_ids = [place.place_id for place in self.places]
        if len(set(place_ids)) != len(place_ids):
            raise ValueError(f"места паспорта повторяются: {sorted(place_ids)}")
        for row, groups in self.rows.items():
            shapes = {group.shape for group in groups}
            if len(shapes) > 1:
                raise ValueError(f"ряд {row}: группы разной формы — повтором их не заполнить")
        return self

    @property
    def places(self) -> list[Place]:
        return [place for group in self.groups for place in group.places]

    @property
    def rows(self) -> dict[str, list[PlaceGroup]]:
        """Ряды повторов в порядке групп паспорта — порядок ряда и есть порядок заполнения."""
        out: dict[str, list[PlaceGroup]] = {}
        for group in self.groups:
            if group.row is not None:
                out.setdefault(group.row, []).append(group)
        return out

    def place(self, place_id: str) -> Place | None:
        return next((place for place in self.places if place.place_id == place_id), None)


class Recipe(DomainModel):
    """Слайд-пример шаблона как готовая композиция.

    Автор шаблона уже решил, где плашки, где декор и где текст. Рецепт — это его
    решение, названное так, чтобы вёрстка могла его повторить: вид, зоны, повторы.
    """

    recipe_id: str = Field(min_length=1, description="ex<номер примера, три цифры>")
    example_index: int = Field(ge=1)
    part_name: str | None = Field(default=None, description="Часть слайда-примера в файле")
    kind: RecipeKind
    zones: list[Zone] = Field(default_factory=list)
    repeats: int = Field(default=0, ge=0, description="Сколько повторов в ряду композиции")
    #: Адреса фигур каждого повтора, по порядку: плашка, её заголовок, её текст. Нужны
    #: вёрстке, чтобы удалить лишний повтор целиком, а не одну надпись в нём.
    repeat_xml_ids: list[list[int]] = Field(default_factory=list)
    has_picture: bool = Field(default=False, description="В области контента стоит картинка")
    picture_xml_id: int | None = Field(
        default=None, description="Адрес картинки, которую подменяет ассет слайда"
    )
    origin: Origin = Origin.MEASURED
    #: Новое поле последним и необязательно: каталог лежит в чекпойнте.
    layout_name: str = Field(
        default="",
        description=(
            "Имя макета, на котором стоит пример: по нему подборщик узнаёт пример "
            "на титуле, разделе или финале и берёт его содержательному слайду последним (Т8)"
        ),
    )
    #: Паспорт примера (ADR-009). `None` — каталог собран до плана Б или пример паспорт
    #: не получил; путь `by_example` такой пример не берёт.
    passport: ExamplePassport | None = None

    @model_validator(mode="after")
    def _passport_points_at_own_zones(self) -> Recipe:
        """Место паспорта ссылается только на зону своего рецепта.

        Иначе композиция написала бы текст под зону, которой на слайде нет, а вёрстка
        не нашла бы, куда его поставить.
        """
        if self.passport is None:
            return self
        zones = {zone.zone_id for zone in self.zones}
        stray = sorted(
            place.place_id
            for place in self.passport.places
            if place.zone_id is not None and place.zone_id not in zones
        )
        if stray:
            raise ValueError(f"{self.recipe_id}: места {stray} ссылаются на чужие зоны")
        return self


class DesignSystem(DomainModel):
    """Дизайн-система шаблона целиком: поля соответствуют разделам страницы."""

    template_id: str
    source_name: str
    typography: Typography = Field(default_factory=Typography)
    grid: GridSpec
    bullets: BulletSpec = Field(default_factory=BulletSpec)
    theme: ThemeInfo

    #: Заполняет таск 02 — измеренное по слайдам-примерам.
    palette_roles: list[PaletteRole] = Field(default_factory=list)
    combinations: list[Combination] = Field(default_factory=list)
    contrast_pairs: list[ContrastPair] = Field(default_factory=list)
    fonts_in_use: list[FontInUse] = Field(default_factory=list)
    number_sizes: NumberScale = Field(default_factory=NumberScale)
    components: list[ComponentCard] = Field(default_factory=list)

    #: Заполняет таск 03 — достроенное из примитивов шаблона.
    contrast_defects: list[ContrastDefect] = Field(
        default_factory=list,
        description="Где шаблон не даёт читаемой пары — change `a-minimum-is-not-a-norm`",
    )
    #: Заполняет change `recipes-in-the-design-system` — седьмой раздел, композиции.
    recipes: list[Recipe] = Field(default_factory=list)
    synthesized: list[SynthElement] = Field(default_factory=list)
    assembly_rules: list[AssemblyRule] = Field(default_factory=list)
