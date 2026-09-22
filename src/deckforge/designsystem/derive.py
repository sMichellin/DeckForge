"""`derive(manifest) -> DesignSystem` — единственный шов слоя.

Сначала собирается то, для чего хватает темы и сетки, затем структуру по очереди
дополняют измеренное по примерам (`measure`) и достроенное из примитивов (`synthesize`).
"""

from __future__ import annotations

from functools import reduce
from math import gcd

from deckforge.designsystem.measure import measure
from deckforge.designsystem.models import (
    BulletSpec,
    DesignSystem,
    GridSpec,
    Origin,
    SpacingScale,
    ThemeInfo,
    ThemeSlot,
    TypeStep,
    Typography,
)
from deckforge.designsystem.synth import synthesize
from deckforge.domain.enums import ColorRef, TextRole
from deckforge.domain.template import Margins, TemplateManifest, Theme
from deckforge.domain.units import pt_to_emu

#: Назначение роли словами. Роли — из домена, а не из шаблона: это описание контракта
#: типографической шкалы, одинаковое для любого шаблона.
ROLE_PURPOSE: dict[TextRole, str] = {
    TextRole.TITLE: "Заголовок слайда: одна мысль, крупно",
    TextRole.SUBTITLE: "Подзаголовок и лид: раскрывает заголовок",
    TextRole.BODY: "Основной текст и пункты списка",
    TextRole.CAPTION: "Подпись, сноска, метка у показателя",
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


def _typography(manifest: TemplateManifest) -> Typography:
    slide_cx = manifest.slide_size.cx_emu
    steps = [
        TypeStep(
            role=step.role,
            size_pt=step.size_pt,
            font_family=_font_family(manifest.theme, step.font_ref),
            font_ref=step.font_ref,
            bold=step.bold,
            italic=step.italic,
            line_spacing=step.line_spacing,
            color_ref=step.color_ref,
            purpose=ROLE_PURPOSE[step.role],
            width_share=round(pt_to_emu(step.size_pt) / slide_cx, SHARE_DIGITS),
            origin=Origin.MEASURED,
        )
        for step in manifest.typography_scale
    ]
    return Typography(steps=steps, origin=Origin.MEASURED if steps else Origin.DERIVED)


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
        #: Направляющие, выведенные кластеризацией, — не то же самое, что снятые
        #: из мастера: рядом с цифрами должно стоять, чему верить.
        origin=Origin.MEASURED if grid.guides_source == "xml" else Origin.DERIVED,
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
    return synthesize(manifest, ds)
