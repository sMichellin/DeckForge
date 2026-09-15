"""Выбор визуализации. Change (11)/(14).

Сначала детерминированные правила (`domain.rules.choose_chart_type`),
LLM — только на пограничных случаях (§10).
"""

from __future__ import annotations

from deckforge.domain.content import Dataset
from deckforge.domain.enums import ChartType


def select_chart(dataset: Dataset) -> ChartType:
    raise NotImplementedError("change (14) native-charts-tables")
