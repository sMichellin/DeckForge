"""Достроенное из примитивов шаблона: плашки, списки, элементы слайда, правила сборки.

Наполняется таском 03. Сигнатура `synthesize(manifest, ds) -> DesignSystem` фиксирована:
на ней держится параллельная волна, и `derive.py` её уже вызывает.
"""

from __future__ import annotations

from deckforge.designsystem.models import DesignSystem
from deckforge.domain.template import TemplateManifest


def synthesize(manifest: TemplateManifest, ds: DesignSystem) -> DesignSystem:
    """Дополнить структуру тем, что достраивается из примитивов шаблона."""
    return ds
