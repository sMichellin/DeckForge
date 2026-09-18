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


# --- требования к внешним программам (запрос потока B из change 16) ------------


def test_pdf_conversion_does_not_need_pdftoppm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`pdftoppm` режет страницы, а не конвертирует: на пути в pdf он не нужен.

    Из-за лишнего требования экспорт в pdf отказывал на машинах без poppler.
    """
    import subprocess

    from deckforge.rendering import soffice as module

    monkeypatch.setattr(
        module.shutil, "which", lambda name: "/usr/bin/soffice" if name == "soffice" else None
    )

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> object:
        calls.append(cmd)
        Path(cmd[cmd.index("--outdir") + 1], "deck.pdf").write_bytes(b"%PDF-1.7")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    source = tmp_path / "deck.pptx"
    source.write_bytes(b"pptx")
    assert SofficeRenderer().to_pdf(source, tmp_path / "out").exists()
    assert calls, "команда конвертации не запускалась"


def test_page_splitting_still_demands_pdftoppm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deckforge.rendering import soffice as module

    monkeypatch.setattr(
        module.shutil, "which", lambda name: "/usr/bin/soffice" if name == "soffice" else None
    )
    with pytest.raises(SofficeUnavailableError, match="pdftoppm"):
        SofficeRenderer().pdf_to_pngs(tmp_path / "deck.pdf", tmp_path / "out")


def test_pdf_capability_is_separate_from_preview_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deckforge.rendering import soffice as module

    monkeypatch.setattr(
        module.shutil, "which", lambda name: "/usr/bin/soffice" if name == "soffice" else None
    )
    renderer = SofficeRenderer()
    assert renderer.can_convert_pdf is True
    assert renderer.available is False, "превью без pdftoppm не собрать"


def test_profile_is_passed_as_a_real_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«file://C:\\…» — не URI: LibreOffice его молча игнорирует и не конвертирует."""
    import subprocess

    from deckforge.rendering import soffice as module

    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")
    seen: list[str] = []

    def fake_run(cmd: list[str], **kwargs: object) -> object:
        seen.extend(a for a in cmd if a.startswith("-env:UserInstallation="))
        Path(cmd[cmd.index("--outdir") + 1], "deck.pdf").write_bytes(b"%PDF-1.7")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"pptx")
    SofficeRenderer().to_pdf(source, tmp_path / "out")

    (profile,) = seen
    uri = profile.split("=", 1)[1]
    assert uri.startswith("file:///"), uri
    assert "\\" not in uri, "в URI попал путь Windows как есть"
