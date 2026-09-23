"""Экспорт .pptx. Change (16) `export-pptx-pdf`.

Тонкий адаптер над `PptxWriter`: проверки IR и цепочка деградации — там. Здесь — одно:
отдаётся только файл, который открывается.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation

from deckforge.designsystem import DesignSystem
from deckforge.domain.content import ContentPackage
from deckforge.domain.slide import DeckIR
from deckforge.domain.template import TemplateManifest
from deckforge.export.pdf import ExportError
from deckforge.layout.fonts import FontLibrary
from deckforge.rendering.writer import PptxWriter


def export_pptx(
    deck: DeckIR,
    manifest: TemplateManifest,
    template_path: Path,
    out: Path,
    content: ContentPackage | None = None,
    fonts: FontLibrary | None = None,
    design_system: DesignSystem | None = None,
) -> Path:
    """`design_system` — та же, что видело вписывание (DG3); нет — считается из манифеста."""
    writer = PptxWriter(template_path, manifest, fonts=fonts, design_system=design_system)
    path = writer.write(deck, out, content=content)
    try:
        Presentation(str(path))
    except Exception as exc:
        # python-pptx на битом пакете бросает что угодно — от BadZipFile до KeyError.
        path.unlink(missing_ok=True)
        raise ExportError(f"записанный файл {path.name} не открывается: {exc}") from exc
    return path
