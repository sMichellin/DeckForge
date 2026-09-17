"""Экспорт .pdf через тот же процесс LibreOffice, что и превью. Change (16).

pdf получается из уже записанного .pptx: контент не пересобирается (C4), и pdf показывает ровно
то, что лежит в файле.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from deckforge.rendering.soffice import SofficeRenderer, SofficeUnavailableError


class ExportError(RuntimeError):
    """Экспорт не состоялся. Причина — в сообщении; частичный файл не оставляется."""


class PdfRenderer(Protocol):
    def to_pdf(self, source: Path, out_dir: Path) -> Path: ...


def export_pdf(pptx_path: Path, out: Path, renderer: PdfRenderer | None = None) -> Path:
    """pptx → pdf по пути `out`. Конвертация — во временный каталог, затем перенос."""
    if not pptx_path.is_file():
        raise ExportError(f"нет файла {pptx_path}")
    engine = renderer if renderer is not None else SofficeRenderer()
    with tempfile.TemporaryDirectory() as work:
        try:
            pdf = engine.to_pdf(pptx_path, Path(work))
        except (SofficeUnavailableError, OSError) as exc:
            raise ExportError(f"pdf из {pptx_path.name} не получен: {exc}") from exc
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pdf), str(out))
    return out
