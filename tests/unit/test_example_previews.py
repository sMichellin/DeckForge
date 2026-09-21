"""Превью слайдов-примеров шаблона для профиля оформления (DS7): один рендер на шаблон.

LibreOffice не нужен: рендер подменяется, проверяется кэш.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.pipeline.nodes import render as render_module
from deckforge.pipeline.nodes.render import EXAMPLES_DIR, example_previews_of


class FakeRender:
    """Рисует по png на страницу и считает вызовы; может упасть посередине."""

    def __init__(self, pages: int = 3, fail: bool = False) -> None:
        self.pages = pages
        self.fail = fail
        self.calls = 0

    def __call__(self, pptx: Path, out_dir: Path, dpi: int = 150) -> dict[str, Path]:
        self.calls += 1
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "page-1.png").write_bytes(b"png")
        if self.fail:
            raise OSError("soffice упал на середине")
        for number in range(2, self.pages + 1):
            (out_dir / f"page-{number}.png").write_bytes(b"png")
        return {}


def test_examples_are_rendered_once_per_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeRender(pages=3)
    monkeypatch.setattr(render_module, "render_previews", fake)

    first = example_previews_of(tmp_path / "tpl.pptx", "sha256:abc", tmp_path)
    second = example_previews_of(tmp_path / "tpl.pptx", "sha256:abc", tmp_path)

    assert len(first) == 3 and first == second
    assert fake.calls == 1, "тот же шаблон второй раз не рендерится"
    assert all(EXAMPLES_DIR in str(path) and "sha256_abc" in str(path) for path in first)


def test_another_template_is_rendered_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeRender(pages=2)
    monkeypatch.setattr(render_module, "render_previews", fake)

    example_previews_of(tmp_path / "a.pptx", "sha256:aaa", tmp_path)
    example_previews_of(tmp_path / "b.pptx", "sha256:bbb", tmp_path)

    assert fake.calls == 2


def test_a_broken_render_is_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Рендер упал после первой страницы: одна картинка не должна стать «профилем»."""
    monkeypatch.setattr(render_module, "render_previews", FakeRender(fail=True))
    with pytest.raises(OSError):
        example_previews_of(tmp_path / "tpl.pptx", "sha256:abc", tmp_path)

    healthy = FakeRender(pages=3)
    monkeypatch.setattr(render_module, "render_previews", healthy)
    assert len(example_previews_of(tmp_path / "tpl.pptx", "sha256:abc", tmp_path)) == 3
    assert healthy.calls == 1
