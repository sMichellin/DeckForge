"""Измеренное по слайдам-примерам: роли цветов, доли, сочетания, контрасты, гарнитуры.

Наполняется таском 02. Сигнатура `measure(manifest, ds) -> DesignSystem` фиксирована:
на ней держится параллельная волна, и `derive.py` её уже вызывает.
"""

from __future__ import annotations

from deckforge.designsystem.models import DesignSystem
from deckforge.domain.template import TemplateManifest


def measure(manifest: TemplateManifest, ds: DesignSystem) -> DesignSystem:
    """Дополнить структуру тем, что измеряется по слайдам-примерам."""
    return ds
