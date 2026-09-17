"""Выбор визуализации. Change (11)/(14).

Сначала детерминированные правила (`domain.rules.choose_chart_type`),
LLM — только на пограничных случаях (§10).

Почему правилом, а не моделью: выбор типа диаграммы обязан быть воспроизводимым.
Одни и те же данные при повторном прогоне должны дать ту же диаграмму, иначе три
варианта вёрстки начнут различаться случайно, а не по объявленной оси (C7, C11).
"""

from __future__ import annotations

import re
from typing import Final

from deckforge.domain.content import Dataset
from deckforge.domain.enums import ChartType
from deckforge.domain.rules import choose_chart_type

#: Категории, которые выдают ряд во времени: годы, кварталы, месяцы, даты.
_YEAR: Final = re.compile(r"^\s*(19|20)\d{2}\s*(г\.?|год)?\s*$", re.IGNORECASE)
_QUARTER: Final = re.compile(r"^\s*(q|кв\.?|квартал)\s*[1-4]\s*$", re.IGNORECASE)
_QUARTER_SUFFIX: Final = re.compile(r"^\s*[1-4]\s*(кв\.?|квартал)\s*$", re.IGNORECASE)
_DATE: Final = re.compile(r"^\s*\d{1,2}[./]\d{1,2}([./]\d{2,4})?\s*$")
_MONTHS: Final = frozenset(
    {
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
        "янв", "фев", "мар", "апр", "июн", "июл", "авг", "сен", "окт", "ноя", "дек",
    }
)


def _is_time_label(label: str) -> bool:
    text = label.strip().casefold()
    if text in _MONTHS:
        return True
    return bool(
        _YEAR.match(label) or _QUARTER.match(label) or _QUARTER_SUFFIX.match(label)
        or _DATE.match(label)
    )


def looks_like_time_series(categories: list[str]) -> bool:
    """Ряд считается временным, если временными выглядят почти все подписи.

    Порог, а не «все»: в реальных выгрузках рядом с кварталами попадается «Итого»
    или сноска, и из-за одной такой подписи динамика не перестаёт быть динамикой.
    """
    if len(categories) < 2:
        return False
    hits = sum(1 for label in categories if _is_time_label(label))
    return hits / len(categories) >= 0.75


def select_chart(dataset: Dataset) -> ChartType:
    """Тип диаграммы под данные. Детерминированно, без обращения к модели."""
    return choose_chart_type(
        series_count=len(dataset.series),
        category_count=len(dataset.categories),
        is_time_series=looks_like_time_series(dataset.categories),
        is_shares=dataset.is_shares and len(dataset.series) == 1,
    )
