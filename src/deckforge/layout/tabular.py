"""Данные для таблиц и буллетов из датасета. Change (14) `native-charts-tables`.

Одни и те же ячейки нужны и `layout` (вписать), и `rendering` (записать): считаются они здесь,
в нижнем из двух слоёв, чтобы измеренное и записанное не разошлись.
"""

from __future__ import annotations

from decimal import Decimal

from deckforge.domain.content import Dataset
from deckforge.domain.slide import TableBlock
from deckforge.layout.errors import LayoutFitError

#: Чем показать отсутствующее значение: пустая ячейка читается как ошибка вёрстки.
MISSING_VALUE = "—"


def format_number(value: float | None) -> str:
    """Число по-русски: десятичная запятая, без хвостовых нулей и экспоненты."""
    if value is None:
        return MISSING_VALUE
    if float(value).is_integer():
        return str(int(value))
    # Decimal от repr: без экспоненты и без округления крошечных величин до нуля.
    text = format(Decimal(repr(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def table_cells(block: TableBlock, dataset: Dataset | None) -> list[list[str]]:
    """Ячейки таблицы: шапка и строки блока, а если их нет — датасет.

    Из датасета: категории — строки, серии — колонки, первая колонка — категория.
    Таблица без строк данных или с пустой строкой — ошибка: её нечем заполнить.
    """
    if block.header or block.rows:
        rows = [list(r) for r in block.rows]
        header = [list(block.header)] if block.header else []
    elif dataset is None:
        raise LayoutFitError(
            f"таблица {block.block_id}: нет ни строк, ни датасета {block.dataset_ref}"
        )
    else:
        header = [["", *(s.name for s in dataset.series)]]
        rows = [
            [category, *(format_number(_at(s.values, i)) for s in dataset.series)]
            for i, category in enumerate(dataset.categories)
        ]
    if not rows:
        raise LayoutFitError(f"таблица {block.block_id}: нет строк данных")
    if any(not row for row in rows):
        raise LayoutFitError(f"таблица {block.block_id}: пустая строка")
    return header + rows


def table_has_header(block: TableBlock) -> bool:
    """Есть ли у таблицы шапка: явная или из датасета (имена серий)."""
    return bool(block.header) or (not block.rows and block.dataset_ref is not None)


def dataset_bullets(dataset: Dataset) -> list[str]:
    """Последняя ступень деградации диаграммы: по буллету на категорию, с единицей."""
    unit = f" {dataset.unit}" if dataset.unit else ""
    out = []
    for i, category in enumerate(dataset.categories):
        if len(dataset.series) == 1:
            values = format_number(_at(dataset.series[0].values, i))
        else:
            values = ", ".join(
                f"{s.name} — {format_number(_at(s.values, i))}" for s in dataset.series
            )
        out.append(f"{category}: {values}{unit}")
    return out


def _at(values: list[float | None], index: int) -> float | None:
    return values[index] if index < len(values) else None
