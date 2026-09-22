"""Слой `designsystem`: производные дизайн-системы шаблона.

Стоит сразу над `domain` и импортирует только его. Отдельный слой нужен потому, что
этими же производными будет пользоваться композиция, которая стоит правее: иначе её
пришлось бы тащить в экспорт.
"""

from __future__ import annotations

from deckforge.designsystem.derive import derive
from deckforge.designsystem.models import DesignSystem, Origin

__all__ = ["DesignSystem", "Origin", "derive"]
