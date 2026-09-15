"""Экспорт .pptx. Change (16) `export-pptx-pdf`."""

from __future__ import annotations

from pathlib import Path

from deckforge.domain.slide import DeckIR
from deckforge.domain.template import TemplateManifest


def export_pptx(deck: DeckIR, manifest: TemplateManifest, template_path: Path, out: Path) -> Path:
    raise NotImplementedError("change (16) export-pptx-pdf")
