"""Прогон через UI: что считается успехом. Change `the-ui-is-checked-end-to-end` (план Б, тимлид).

Сам браузерный прогон идёт на стенде (`make ui-e2e`), здесь — его решения: когда прогон кончился,
чем он кончился, какой у него номер и когда сдача через UI состоялась.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ui() -> ModuleType:
    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        return importlib.import_module("ui_e2e")
    finally:
        sys.path.remove(str(scripts))


def test_the_script_does_not_need_playwright_to_load(ui: ModuleType) -> None:
    """Норма: Playwright не зависимость проекта — модуль грузится без него."""
    assert "playwright.sync_api" not in sys.modules
    assert callable(ui.run)


def test_a_page_with_downloads_is_done(ui: ModuleType) -> None:
    """Норма: кнопка «Скачать» — колода готова."""
    assert ui.state_of("Колода собрана · Скачать PowerPoint") == "done"


def test_a_failed_run_is_failed_and_a_running_one_is_not_over(ui: ModuleType) -> None:
    """Нарушитель: прогон упал — `failed`; ещё идёт — `None`, ждать дальше."""
    assert ui.state_of("Прогон не дошёл до конца: stage fit") == "failed"
    assert ui.state_of("идёт · стадия compose") is None


def test_all_three_formats_downloaded_is_a_pass(ui: ModuleType) -> None:
    """Норма: колода готова, pptx/pdf/html скачаны непустыми, ошибок нет — сдача состоялась."""
    result = ui.Result(name="ws", state="done", downloads={"a.pptx": 9, "a.pdf": 7, "a.html": 1})
    assert result.missing_formats() == []
    assert result.passed()


def test_an_empty_or_missing_format_fails(ui: ModuleType) -> None:
    """Нарушитель: pdf пустой, html не скачался — сдача через UI не состоялась."""
    result = ui.Result(name="ws", state="done", downloads={"a.pptx": 9, "a.pdf": 0})
    assert result.missing_formats() == ["pdf", "html"]
    assert not result.passed()


def test_a_page_error_fails_even_with_downloads(ui: ModuleType) -> None:
    """Нарушитель: файлы скачаны, но на странице исключение — прогон не зачтён."""
    result = ui.Result(
        name="ws",
        state="done",
        downloads={"a.pptx": 9, "a.pdf": 7, "a.html": 1},
        page_problems=["stException: KeyError"],
    )
    assert not result.passed()


def test_the_run_id_comes_from_the_downloaded_files(ui: ModuleType) -> None:
    """Норма: номер прогона — из имени скачанного файла (на странице его нет, 29.09), иначе «?»."""
    assert ui.run_id_of("12d8d4e6c0ad.pptx", "Колода собрана") == "12d8d4e6c0ad"
    assert ui.run_id_of("прогон a3a8f3a2319b · готово") == "a3a8f3a2319b"
    assert ui.run_id_of("ничего") == "?"
