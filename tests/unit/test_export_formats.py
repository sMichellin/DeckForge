"""Экспорт .pptx и .pdf — адаптеры над одним IR. Change (16) `export-pptx-pdf`."""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.export.pdf import ExportError, export_pdf
from deckforge.rendering.soffice import SofficeUnavailableError


class FakeRenderer:
    """Подделка `SofficeRenderer`: кладёт pdf туда же, куда настоящий, — `<stem>.pdf` в out_dir."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[Path, Path]] = []

    def to_pdf(self, source: Path, out_dir: Path) -> Path:
        self.calls.append((source, out_dir))
        if self.fail:
            raise SofficeUnavailableError("нет soffice")
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf = out_dir / f"{source.stem}.pdf"
        pdf.write_bytes(b"%PDF-1.7 fake")
        return pdf


def test_pdf_lands_exactly_at_the_requested_path(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"pptx")
    out = tmp_path / "exports" / "итог.pdf"
    renderer = FakeRenderer()
    assert export_pdf(deck, out, renderer=renderer) == out
    assert out.read_bytes().startswith(b"%PDF")
    # Конвертация идёт во временный каталог, а не рядом с исходником.
    assert renderer.calls[0][1] != deck.parent


def test_libreoffice_failure_is_an_export_error(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"pptx")
    out = tmp_path / "deck.pdf"
    with pytest.raises(ExportError, match="нет soffice"):
        export_pdf(deck, out, renderer=FakeRenderer(fail=True))
    assert not out.exists()


def test_missing_pptx_is_an_export_error(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="нет файла"):
        export_pdf(tmp_path / "нет.pptx", tmp_path / "deck.pdf", renderer=FakeRenderer())
