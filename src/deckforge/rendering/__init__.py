"""Слой `rendering`: `SlideIR` → нативные объекты python-pptx (C3).

Changes: (13) pptx-writer, (14) native-charts-tables, (21) smartart-icons.
Вся работа с python-pptx изолирована здесь — переход на форк `power-pptx` правит один слой (§8.3).
"""

from deckforge.rendering.writer import PptxWriter

__all__ = ["PptxWriter"]
