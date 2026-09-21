"""Вместимость макета. Change (3) `template-parsing-core`.

Значения **вычисляются** из площади плейсхолдера и кегля роли, а не задаются константами:
именно это делает решение применимым к незнакомому шаблону (C6).

**Здесь сознательно остаётся оценка по средней ширине знака, а не точные метрики.**
Точность живёт в слое `layout` (change 12, `fontTools`), и перенести её сюда нельзя:
`parsing` ниже `layout` по слоям, импорт «вверх» запрещён (ARCHITECTURE.md §3).

Разделение осмысленное, а не вынужденное. Вместимость нужна планировщику, чтобы прикинуть,
сколько текста просить у модели, — там достаточно порядка величины. Вписывание же должно
быть точным, и оно делается в `layout.fit_text` перед самой записью файла.
"""

from __future__ import annotations

from deckforge.domain.enums import TextRole
from deckforge.domain.template import LayoutCapacity, PlaceholderSpec, TypographyStep
from deckforge.domain.units import (
    EMU_PER_PT,
    TEXT_FRAME_INSET_X_EMU,
    TEXT_FRAME_INSET_Y_EMU,
)

#: Средняя ширина знака в долях кегля для гротесков с кириллицей.
#: Оценка сверху-снизу: у узких гарнитур ~0.45, у широких ~0.58.
_AVG_CHAR_WIDTH_RATIO = 0.52

#: Высота строки в долях кегля при одинарном интерлиньяже.
_LINE_HEIGHT_RATIO = 1.2

#: Места, куда шаблон разрешает положить содержание. Публично: композиция считает
#: по тем же местам, какие место мерил парсер, — иначе вместимость и пригодность
#: макета расходятся (B8, `composition/content_fit.py`).
CONTENT_PH_TYPES = frozenset({"BODY", "OBJ", "TBL", "CHART", "PIC", "SUBTITLE", "CTRTITLE"})


def chars_that_fit(placeholder: PlaceholderSpec, size_pt: float) -> int:
    """Сколько знаков помещается в плейсхолдер при данном кегле."""
    if size_pt <= 0:
        return 0
    usable_cx = max(0, placeholder.cx - 2 * TEXT_FRAME_INSET_X_EMU)
    usable_cy = max(0, placeholder.cy - 2 * TEXT_FRAME_INSET_Y_EMU)

    char_width_emu = size_pt * _AVG_CHAR_WIDTH_RATIO * EMU_PER_PT
    line_height_emu = size_pt * _LINE_HEIGHT_RATIO * EMU_PER_PT
    if char_width_emu <= 0 or line_height_emu <= 0:
        return 0

    chars_per_line = int(usable_cx // char_width_emu)
    lines = int(usable_cy // line_height_emu)
    return max(0, chars_per_line * lines)


def lines_that_fit(placeholder: PlaceholderSpec, size_pt: float) -> int:
    if size_pt <= 0:
        return 0
    usable_cy = max(0, placeholder.cy - 2 * TEXT_FRAME_INSET_Y_EMU)
    return int(usable_cy // (size_pt * _LINE_HEIGHT_RATIO * EMU_PER_PT))


def compute_capacity(
    placeholders: list[PlaceholderSpec],
    typography_scale: list[TypographyStep],
    slide_area_emu: int,
) -> LayoutCapacity:
    """Вместимость макета по его плейсхолдерам и типографической шкале шаблона."""
    sizes = {step.role: step.size_pt for step in typography_scale}
    body_pt = sizes.get(TextRole.BODY, 18.0)
    title_pt = sizes.get(TextRole.TITLE, 40.0)

    title_ph = next((p for p in placeholders if p.role is TextRole.TITLE), None)
    body_phs = [p for p in placeholders if p.ph_type in CONTENT_PH_TYPES]

    max_chars_body = sum(chars_that_fit(p, body_pt) for p in body_phs)
    # Буллет занимает строку целиком, поэтому считаем по строкам, а не по знакам.
    max_bullets = sum(lines_that_fit(p, body_pt) for p in body_phs)

    largest = max((p for p in body_phs), key=lambda p: p.cx * p.cy, default=None)
    largest_share = (largest.cx * largest.cy) / slide_area_emu if largest and slide_area_emu else 0

    return LayoutCapacity(
        max_bullets=max_bullets,
        max_chars_body=max_chars_body,
        max_chars_title=chars_that_fit(title_ph, title_pt) if title_ph else 0,
        # Диаграмма и таблица требуют заметной площади: в узкую полоску их ставить нельзя.
        supports_chart=largest_share >= 0.15,
        supports_table=largest_share >= 0.15,
        supports_image=any(p.ph_type == "PIC" for p in placeholders) or largest_share >= 0.2,
    )
