"""Классификация макетов. Change (5) `layout-classification` (эвристическая часть).

Вид макета выводится из **состава и геометрии плейсхолдеров**, а не из его имени:
имена в шаблонах произвольны, переведены на разные языки и часто вообще не описывают
содержание («2_Титульный слайд», «Custom Layout 14»). Опора на имя — это заточка
под знакомый шаблон (C6).

VLM подключается в той же change поверх этой эвристики — только там, где уверенность низкая.
"""

from __future__ import annotations

from deckforge.domain.enums import LayoutKind, TextRole
from deckforge.domain.template import PlaceholderSpec, SlideSize
from deckforge.parsing.ooxml.layouts import DECOR_PH_TYPES

#: Порог, ниже которого эвристике не верят и зовут VLM.
UNCERTAIN_BELOW = 0.6

_CHART_PH = frozenset({"CHART"})
_TABLE_PH = frozenset({"TBL"})
_PICTURE_PH = frozenset({"PIC"})


def _content_placeholders(placeholders: list[PlaceholderSpec]) -> list[PlaceholderSpec]:
    """Колонтитулы, дата и номер слайда не делают макет содержательным."""
    return [p for p in placeholders if p.ph_type.lower() not in DECOR_PH_TYPES]


def _same_row(a: PlaceholderSpec, b: PlaceholderSpec, tolerance: int) -> bool:
    return abs(a.y - b.y) <= tolerance and abs(a.cy - b.cy) <= tolerance


def classify_heuristic(
    placeholders: list[PlaceholderSpec], slide_size: SlideSize
) -> tuple[LayoutKind, float]:
    """Вид макета и уверенность в нём."""
    content = _content_placeholders(placeholders)
    if not content:
        # Ни одного плейсхолдера: декоративный разделитель либо макет «под ручную вёрстку».
        return LayoutKind.SECTION, 0.4

    slide_area = slide_size.cx_emu * slide_size.cy_emu
    tolerance = int(slide_size.cy_emu * 0.03)

    titles = [p for p in content if p.role is TextRole.TITLE]
    bodies = [p for p in content if p.role is TextRole.BODY]
    subtitles = [p for p in content if p.role is TextRole.SUBTITLE]

    # Явные типы плейсхолдеров — самый надёжный сигнал: автор шаблона сказал прямо.
    if any(p.ph_type in _CHART_PH for p in content):
        return LayoutKind.CHART, 0.95
    if any(p.ph_type in _TABLE_PH for p in content):
        return LayoutKind.TABLE, 0.95

    pictures = [p for p in content if p.ph_type in _PICTURE_PH]
    if pictures:
        biggest = max(p.cx * p.cy for p in pictures)
        if biggest / slide_area >= 0.6:
            return LayoutKind.IMAGE_FULL, 0.9

    # Титул: заголовок с подзаголовком и без основного текста.
    if titles and subtitles and not bodies:
        return LayoutKind.TITLE, 0.9

    # Раздел: единственный крупный текстовый блок, ничего больше.
    if len(content) == 1 and titles:
        vertical_center = titles[0].y + titles[0].cy / 2
        centered = abs(vertical_center - slide_size.cy_emu / 2) <= slide_size.cy_emu * 0.2
        return (LayoutKind.SECTION, 0.85) if centered else (LayoutKind.TITLE, 0.6)

    if bodies:
        # Несколько одинаковых блоков в один ряд: колонки или показатели.
        rows = [p for p in bodies if _same_row(p, bodies[0], tolerance)]
        if len(rows) >= 3 and all(p.cx * p.cy / slide_area < 0.15 for p in rows):
            return LayoutKind.KPI, 0.8
        if len(rows) == 2:
            return LayoutKind.TWO_COLUMN, 0.85
        if len(bodies) == 1 and titles:
            body = bodies[0]
            # Широкий и высокий одиночный блок под заголовком — классические буллеты.
            if body.cy / slide_size.cy_emu >= 0.25:
                return LayoutKind.BULLETS, 0.8
            return LayoutKind.QUOTE, 0.5

    if titles and not bodies and not subtitles:
        return LayoutKind.CLOSING, 0.45

    return LayoutKind.CUSTOM, 0.3


def needs_vlm(confidence: float) -> bool:
    """Звать ли VLM. Дорогой вызов делается только там, где эвристика не уверена."""
    return confidence < UNCERTAIN_BELOW
