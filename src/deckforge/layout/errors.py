"""Ошибки слоя `layout`.

Отдельный модуль, чтобы `fitting` и `tabular` не импортировали друг друга.
"""

from __future__ import annotations


class LayoutFitError(ValueError):
    """IR нельзя вписать: макета или плейсхолдера нет, места под блоки не осталось."""
