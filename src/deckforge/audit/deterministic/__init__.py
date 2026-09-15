"""Детерминированные проверки (§5.1): чистые функции над `SlideIR` и геометрией.

Импорт модуля регистрирует все проверки в `audit.registry.REGISTRY`.
"""

from deckforge.audit.deterministic import density, integrity, layout, template

__all__ = ["density", "integrity", "layout", "template"]
