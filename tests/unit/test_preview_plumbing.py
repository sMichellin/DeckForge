"""Обвязка рендера превью без самого LibreOffice. Change (6) `template-preview-render`.

Живые прогоны — в `tests/integration/test_preview_render.py`, они требуют образа
с LibreOffice и пропускаются без него. Здесь проверяется то, что от него не зависит:
понятные ошибки, соответствие страниц макетам и отказ отдавать неверное соответствие.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.audit.preview import render_deck_previews
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import DeckIR, SlideIR, TextBlock
from deckforge.rendering.soffice import SofficeRenderer, SofficeUnavailableError


def test_missing_binary_is_reported_clearly() -> None:
    """Пользователь должен понять, что делать, а не увидеть FileNotFoundError."""
    renderer = SofficeRenderer(binary="соффис-которого-нет")
    assert not renderer.available
    with pytest.raises(SofficeUnavailableError, match=r"Dockerfile\.libreoffice"):
        renderer.to_pdf(Path("x.pptx"), Path("out"))


def test_available_requires_both_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """pdftoppm нужен не меньше soffice: без него колода останется pdf-файлом."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None if name == "pdftoppm" else "/bin/x")
    assert not SofficeRenderer().available


def deck(*slide_ids: str) -> DeckIR:
    return DeckIR(
        deck_id="d1",
        variant="A",
        template_id="sha256:" + "0" * 64,
        seed=1,
        slides=[
            SlideIR(
                slide_id=sid,
                layout_id="L00",
                variant="A",
                blocks=[TextBlock(block_id="b1", role=TextRole.TITLE, text="т")],
            )
            for sid in slide_ids
        ],
    )


def test_previews_are_keyed_by_slide_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Аудит оперирует slide_id: после split_slide номера страниц разъезжаются."""
    import deckforge.audit.preview as preview_module

    monkeypatch.setattr(
        preview_module,
        "render_previews",
        lambda *a, **k: {"1": tmp_path / "p1.png", "2": tmp_path / "p2.png"},
    )
    mapping = render_deck_previews(tmp_path / "d.pptx", deck("s01", "s07"), tmp_path)
    assert set(mapping) == {"s01", "s07"}
    assert mapping["s07"].name == "p2.png"


def test_page_count_mismatch_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Молча отдать находку не к тому слайду хуже, чем не отдать ничего."""
    import deckforge.audit.preview as preview_module

    monkeypatch.setattr(
        preview_module, "render_previews", lambda *a, **k: {"1": tmp_path / "p1.png"}
    )
    with pytest.raises(SofficeUnavailableError, match="сопоставление"):
        render_deck_previews(tmp_path / "d.pptx", deck("s01", "s02"), tmp_path)
