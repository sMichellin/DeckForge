"""Истории 1, 2, 27 (R01, R21i, R01.1): шаблон → страница дизайн-системы одной командой.

Проверяется сценарий «файл → файл» целиком: команда, путь по умолчанию, печать пути
и внятный отказ. Числа внутри страницы проверяет шов `derive`, вёрстку — дымовой тест
рендера; здесь — только то, чем пользуется Настя из терминала.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from typer.testing import CliRunner

from deckforge.cli import app
from tests.integration.test_native_objects import build_template

runner = CliRunner()


def _broken(path: Path) -> Path:
    """Файл с расширением шаблона, который не открывается как пакет OPC."""
    path.write_bytes(b"\x50\x4b\x03\x04 not really a package")
    return path


def _zip_without_presentation(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("hello.txt", "no presentation here")
    return path


def test_command_writes_page_and_prints_its_path(tmp_path: Path) -> None:
    template = build_template(tmp_path / "шаблон.pptx")
    out = tmp_path / "страница.html"

    result = runner.invoke(app, ["design-system", str(template), "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert out.read_text(encoding="utf-8").lstrip().startswith("<!doctype html>")
    assert str(out) in result.output


def test_default_output_lands_next_to_the_template(tmp_path: Path) -> None:
    template = build_template(tmp_path / "шаблон.pptx")

    result = runner.invoke(app, ["design-system", str(template)])

    assert result.exit_code == 0, result.output
    produced = sorted(tmp_path.glob("*.html"))
    assert len(produced) == 1, f"ожидался один html рядом с шаблоном, получено {produced}"
    assert "шаблон" in produced[0].stem
    assert produced[0].suffix == ".html"


def test_two_runs_give_the_same_file(tmp_path: Path) -> None:
    template = build_template(tmp_path / "шаблон.pptx")
    first, second = tmp_path / "a.html", tmp_path / "b.html"

    runner.invoke(app, ["design-system", str(template), "-o", str(first)])
    runner.invoke(app, ["design-system", str(template), "-o", str(second)])

    assert first.read_bytes() == second.read_bytes()


def test_wrong_extension_is_refused_in_one_russian_line(tmp_path: Path) -> None:
    alien = tmp_path / "отчёт.docx"
    alien.write_bytes(b"whatever")

    result = runner.invoke(app, ["design-system", str(alien), "-o", str(tmp_path / "o.html")])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 1, lines
    assert ".docx" in lines[0]
    assert ".pptx" in lines[0] and ".potx" in lines[0]


def test_broken_package_is_refused_in_one_russian_line(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["design-system", str(_broken(tmp_path / "битый.pptx")), "-o", str(tmp_path / "o.html")],
    )

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 1, lines
    assert "битый.pptx" in lines[0]


def test_zip_without_presentation_is_refused_in_one_line(tmp_path: Path) -> None:
    path = _zip_without_presentation(tmp_path / "чужой.pptx")

    result = runner.invoke(app, ["design-system", str(path), "-o", str(tmp_path / "o.html")])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 1, lines
