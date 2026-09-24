"""`derive(manifest) -> DesignSystem` — единственный шов слоя.

Сначала собирается то, для чего хватает темы и сетки, затем структуру по очереди
дополняют измеренное по примерам (`measure`) и достроенное из примитивов (`synthesize`).
"""

from __future__ import annotations

from functools import reduce
from math import gcd
from typing import NamedTuple

from deckforge.designsystem.measure import measure
from deckforge.designsystem.models import (
    BulletSpec,
    DesignSystem,
    GridSpec,
    Origin,
    SpacingScale,
    ThemeInfo,
    ThemeSlot,
    TypeLevel,
    TypeStep,
    Typography,
)
from deckforge.designsystem.recipes import recipes
from deckforge.designsystem.synth import synthesize
from deckforge.domain.enums import ColorRef, TextRole
from deckforge.domain.template import (
    Margins,
    TemplateManifest,
    Theme,
    TypographyStep,
)
from deckforge.domain.units import pt_to_emu


class _Rung(NamedTuple):
    """Ступень лестницы: уровень страницы, ближайшая роль домена и назначение словами.

    `anchored` — берётся ли кегль прямо из `typography_scale`. Ролей в домене четыре,
    уровней на странице восемь, поэтому четыре ступени опираются на шкалу шаблона,
    а четыре достраиваются из её же ступеней.
    """

    level: TypeLevel
    role: TextRole
    anchored: bool
    purpose: str


#: Лестница сверху вниз — восемь уровней, названных заказчиком. Порядок объявления
#: и есть порядок ступеней: каждая следующая не крупнее предыдущей.
LADDER: tuple[_Rung, ...] = (
    _Rung(
        TypeLevel.DISPLAY,
        TextRole.TITLE,
        False,
        "Обложка и разделитель: одно слово во весь слайд",
    ),
    _Rung(TypeLevel.SLIDE_TITLE, TextRole.TITLE, True, "Заголовок слайда: одна мысль, крупно"),
    _Rung(
        TypeLevel.SECTION_SUBTITLE,
        TextRole.SUBTITLE,
        True,
        "Подзаголовок раздела и лид: раскрывает заголовок",
    ),
    _Rung(
        TypeLevel.CARD_TITLE,
        TextRole.SUBTITLE,
        False,
        "Заголовок карточки: название блока внутри слайда",
    ),
    _Rung(TypeLevel.BODY_LARGE, TextRole.BODY, False, "Крупный абзац: цитата и вводный текст"),
    _Rung(TypeLevel.BODY, TextRole.BODY, True, "Основной текст и пункты списка"),
    _Rung(TypeLevel.CAPTION, TextRole.CAPTION, True, "Подпись, сноска, метка у показателя"),
    _Rung(
        TypeLevel.LABEL,
        TextRole.CAPTION,
        False,
        "Метка и тег: статус, категория, единица измерения",
    ),
)

#: Чей вид наследует достроенный уровень: гарнитуру, начертание, интерлиньяж и цвет.
#: Кегль наследовать нельзя — он берётся из шкалы шаблона.
STYLE_PARENT: dict[TypeLevel, TypeLevel] = {
    TypeLevel.DISPLAY: TypeLevel.SLIDE_TITLE,
    TypeLevel.CARD_TITLE: TypeLevel.SECTION_SUBTITLE,
    TypeLevel.BODY_LARGE: TypeLevel.BODY,
    TypeLevel.LABEL: TypeLevel.CAPTION,
}

#: Сколько знаков после запятой хранится у долей. Доли попадают в разметку страницы,
#: а она обязана быть побайтно одинаковой от прогона к прогону (G01).
SHARE_DIGITS = 6

#: Кратности базового шага. Ряд, а не «все числа подряд»: отступ в семь шагов никто
#: глазами не отличит от восьми, а страница из такой шкалы становится нечитаемой.
STEP_MULTIPLIERS = (1, 2, 3, 4, 6, 8)

#: Наименьший осмысленный шаг — доля ширины слайда. Порог алгоритма, а не константа
#: шаблона: поля холодного «Шаблона презентации 2024» взаимно просты, их НОД равен
#: одному EMU, и шкала из единиц не меряет ничего — по ней достройка получила бы
#: радиус в тысячную миллиметра.
MIN_STEP_SHARE = 0.001


def _font_family(theme: Theme, step_font_ref: str) -> str:
    """Гарнитура роли по ссылке темы; у ссылки без значения — гарнитура основного текста."""
    return theme.fonts.get(step_font_ref) or theme.fonts.minor_latin  # type: ignore[arg-type]


def _fit_step(anchor_pt: float, upper: float | None, lower: float | None) -> float:
    """Кегль недостающего уровня — ступень шкалы самого шаблона, ни одного числа из головы.

    Достроенный уровень — вариант соседа, чей вид он наследует (`STYLE_PARENT`), поэтому
    и кегль он берёт у него же: `anchor_pt`. Промежуточную ступень искать негде — шкала
    шаблона и есть набор кеглей измеренных уровней, между двумя соседями по лестнице
    своей ступени у неё не бывает. Повтор кегля честен: шаблон просто не различает эти
    два уровня, а промежуточное число пришлось бы выдумать — это нарушило бы правило 6.

    Окно — от ближайшего измеренного уровня снизу до ступени сверху: без него лестница
    у шаблона с неполной шкалой перестаёт убывать. Прижимаем сначала к нижней границе,
    потом к верхней: у нешкальных шаблонов границы могут разойтись, и решает верхняя.
    Все три величины — кегли шаблона, поэтому и результат всегда кегль шаблона.
    """
    size = anchor_pt
    if lower is not None:
        size = max(size, lower)
    if upper is not None:
        size = min(size, upper)
    return size


def _style_source(index: int, measured: dict[TypeLevel, TypographyStep]) -> TypographyStep:
    """Вид достроенного уровня: своя ступень, иначе родительская, иначе ближайшая по лестнице.

    Ближайшая, а не первая попавшаяся: у шаблона без подзаголовка заголовок карточки
    должен выглядеть как заголовок, а не как подпись.
    """
    level = LADDER[index].level
    own = measured.get(level)
    if own is not None:
        return own
    parent = STYLE_PARENT.get(level)
    if parent is not None and parent in measured:
        return measured[parent]
    nearest = min(
        (position for position, rung in enumerate(LADDER) if rung.level in measured),
        key=lambda position: (abs(position - index), position),
    )
    return measured[LADDER[nearest].level]


def _ladder_sizes(measured: dict[TypeLevel, TypographyStep]) -> dict[TypeLevel, float]:
    """Кегль каждого из восьми уровней: измеренные — из шкалы, остальные — из неё же."""
    sizes: dict[TypeLevel, float] = {}
    upper: float | None = None
    for index, rung in enumerate(LADDER):
        step = measured.get(rung.level)
        if step is not None:
            sizes[rung.level] = step.size_pt
        else:
            lower = next(
                (
                    measured[below.level].size_pt
                    for below in LADDER[index + 1 :]
                    if below.level in measured
                ),
                None,
            )
            sizes[rung.level] = _fit_step(_style_source(index, measured).size_pt, upper, lower)
        upper = sizes[rung.level]
    return sizes


def _typography(manifest: TemplateManifest) -> Typography:
    measured: dict[TypeLevel, TypographyStep] = {}
    for rung in LADDER:
        if not rung.anchored:
            continue
        step = manifest.typography(rung.role)
        if step is not None:
            measured[rung.level] = step
    if not measured:
        return Typography(steps=[], origin=Origin.DERIVED)

    slide_cx = manifest.slide_size.cx_emu
    sizes = _ladder_sizes(measured)
    steps: list[TypeStep] = []
    for index, rung in enumerate(LADDER):
        style = _style_source(index, measured)
        size_pt = sizes[rung.level]
        steps.append(
            TypeStep(
                role=rung.role,
                size_pt=size_pt,
                font_family=_font_family(manifest.theme, style.font_ref),
                font_ref=style.font_ref,
                bold=style.bold,
                italic=style.italic,
                line_spacing=style.line_spacing,
                color_ref=style.color_ref,
                purpose=rung.purpose,
                width_share=round(pt_to_emu(size_pt) / slide_cx, SHARE_DIGITS),
                origin=Origin.MEASURED if rung.level in measured else Origin.DERIVED,
                level=rung.level,
            )
        )
    return Typography(steps=steps, origin=Origin.MEASURED)


def _base_step(
    margins: Margins, gutter_emu: int, column_width_emu: int, slide_cx_emu: int
) -> tuple[int, str]:
    """Базовый шаг: объявленный в сетке, иначе НОД полей, иначе поле, иначе колонка."""
    if gutter_emu > 0:
        return gutter_emu, "gutter"
    sides = [side for side in astuple_margins(margins) if side > 0]
    if sides:
        divisor = reduce(gcd, sides)
        if divisor >= slide_cx_emu * MIN_STEP_SHARE:
            return divisor, "margins_gcd"
        return min(sides), "margin"
    return column_width_emu, "columns"


def astuple_margins(margins: Margins) -> tuple[int, int, int, int]:
    return (margins.left, margins.right, margins.top, margins.bottom)


def _grid(manifest: TemplateManifest) -> GridSpec:
    size, grid = manifest.slide_size, manifest.grid
    margins = grid.margins_emu
    content_cx = size.cx_emu - margins.left - margins.right
    content_cy = size.cy_emu - margins.top - margins.bottom
    gutters = grid.gutter_emu * (grid.columns - 1)
    column_width = max(1, (content_cx - gutters) // grid.columns)

    base, source = _base_step(margins, grid.gutter_emu, column_width, size.cx_emu)
    sides = [side for side in astuple_margins(margins) if side > 0]
    spacing = SpacingScale(
        base_emu=base,
        base_source=source,
        steps_emu=[base * k for k in STEP_MULTIPLIERS],
        steps_in_margin=min(sides) // base if sides else 0,
        #: Шаг, выведенный из полей или колонок, шаблон не объявлял — и метка на
        #: странице обязана это сказать.
        origin=Origin.MEASURED if source == "gutter" else Origin.DERIVED,
    )
    return GridSpec(
        width_emu=size.cx_emu,
        height_emu=size.cy_emu,
        aspect=size.aspect,
        margins=margins,
        columns=grid.columns,
        gutter_emu=grid.gutter_emu,
        column_width_emu=column_width,
        content_width_emu=content_cx,
        content_height_emu=content_cy,
        #: Формат и пропорции сняты из `slide_size` и измерены на любом шаблоне —
        #: метка всего блока говорит именно про них.
        origin=Origin.MEASURED,
        #: Направляющие, выведенные кластеризацией, — не то же самое, что снятые
        #: из мастера: рядом с полями и колонками должно стоять, чему верить.
        guides_origin=Origin.MEASURED if grid.guides_source == "xml" else Origin.DERIVED,
        spacing=spacing,
    )


def _bullets(manifest: TemplateManifest) -> BulletSpec:
    bullet = manifest.bullet
    if bullet is None:
        return BulletSpec(origin=Origin.DERIVED)
    return BulletSpec(
        char=bullet.char,
        font=bullet.font,
        color_ref=bullet.color_ref,
        margin_left_emu=bullet.margin_left_emu,
        indent_emu=bullet.indent_emu,
        origin=Origin.MEASURED,
    )


def _theme(theme: Theme) -> ThemeInfo:
    return ThemeInfo(
        slots=[
            ThemeSlot(ref=ref, name=ref.value, color_hex=theme.colors.get(ref)) for ref in ColorRef
        ],
        major_font=theme.fonts.major_latin,
        minor_font=theme.fonts.minor_latin,
        origin=Origin.MEASURED,
    )


def derive(manifest: TemplateManifest) -> DesignSystem:
    """Собрать дизайн-систему шаблона из манифеста. Без модели и без обращений к сети."""
    ds = DesignSystem(
        template_id=manifest.template_id,
        source_name=manifest.source_name,
        typography=_typography(manifest),
        grid=_grid(manifest),
        bullets=_bullets(manifest),
        theme=_theme(manifest.theme),
    )
    ds = measure(manifest, ds)
    ds = synthesize(manifest, ds)
    #: Композиции считаются последними: виду рецепта нужны и лестница, и компоненты,
    #: и сетка — всё, что собрано выше (change `recipes-in-the-design-system`).
    return ds.model_copy(update={"recipes": recipes(manifest, ds)})
