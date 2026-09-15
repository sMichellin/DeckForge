"""Нативные диаграммы. Change (14) `native-charts-tables`.

Серии красятся в accent1…accent6 **темы**, поэтому палитра меняется вместе с шаблоном
без единой правки кода. Цепочка деградации: диаграмма → таблица → буллеты (§15).
"""

from __future__ import annotations

from deckforge.domain.content import Dataset
from deckforge.domain.slide import ChartBlock
from deckforge.domain.template import TemplateManifest


def add_chart(slide: object, block: ChartBlock, dataset: Dataset, manifest: TemplateManifest
              ) -> object:
    raise NotImplementedError("change (14) native-charts-tables")
