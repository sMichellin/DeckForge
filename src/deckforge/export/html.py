"""Экспорт .html из `DeckIR`. Change (22) `export-html`.

Собирается из IR, а не конвертацией pptx: так html наследует те же цвета и типошкалу темы.
"""

from __future__ import annotations

from pathlib import Path

from deckforge.domain.slide import DeckIR
from deckforge.domain.template import TemplateManifest


def export_html(deck: DeckIR, manifest: TemplateManifest, out: Path) -> Path:
    raise NotImplementedError("change (22) export-html")
