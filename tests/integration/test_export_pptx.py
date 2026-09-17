"""Экспорт .pptx на стандартном шаблоне python-pptx. Change (16) `export-pptx-pdf`."""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation

from deckforge.export.pdf import ExportError
from deckforge.export.pptx import export_pptx
from deckforge.rendering.writer import WriterError
from tests.integration.test_native_objects import (
    build_template,
    content_with_image,
    deck_for,
    parse,
)


def test_export_pptx_writes_a_reopenable_deck(tmp_path: Path) -> None:
    template = build_template(tmp_path / "template.pptx")
    manifest = parse(template, tmp_path)
    out = export_pptx(deck_for(manifest), manifest, template, tmp_path / "out" / "deck.pptx",
                      content=content_with_image(tmp_path))
    assert out == tmp_path / "out" / "deck.pptx"
    assert len(Presentation(str(out)).slides) == 12


def test_invalid_deck_is_not_exported(tmp_path: Path) -> None:
    template = build_template(tmp_path / "template.pptx")
    manifest = parse(template, tmp_path)
    deck = deck_for(manifest).model_copy(update={"template_id": "sha256:" + "f" * 64})
    out = tmp_path / "deck.pptx"
    with pytest.raises(WriterError):
        export_pptx(deck, manifest, template, out)
    assert not out.exists()


def test_broken_output_is_not_handed_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Файл, который не открывается, хуже его отсутствия: экспорт проверяет, что отдаёт."""
    template = build_template(tmp_path / "template.pptx")
    manifest = parse(template, tmp_path)

    def broken_write(self: object, deck: object, out_path: Path, **_: object) -> Path:
        out_path.write_bytes(b"not a zip")
        return out_path

    monkeypatch.setattr("deckforge.rendering.writer.PptxWriter.write", broken_write)
    out = tmp_path / "deck.pptx"
    with pytest.raises(ExportError, match="не открывается"):
        export_pptx(deck_for(manifest), manifest, template, out)
    assert not out.exists()
