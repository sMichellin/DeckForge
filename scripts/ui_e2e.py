#!/usr/bin/env python3
"""Прогон через интерфейс: как его делает человек, от загрузки файлов до скачанной колоды.

Зачем. Прогоны приёмки плана Б шли через API (`run-plan-b.sh`), и API отдавал все три формата.
Сдача же принимается через UI: человек открывает страницу, кладёт шаблон и материал,
жмёт «Собрать» и скачивает файл. Этот путь проверял только глаз. 29.09 прогон через внешний UI
показал на листе колоды то, чего API не видит: пустые слайды s01, s10 WorkSpace.
Change `the-ui-is-checked-end-to-end`.

Сценарий: «Задать» N слайдов, seed, профиль, без остановки на починку → загрузка → «Собрать»
→ ждать «Скачать» → лист колоды → нажать каждую кнопку скачивания и сохранить файл.
Итог — `result.json` и четыре снимка страницы в `OUT/NAME/`.

Playwright в образ приложения не входит: скрипт запускается в официальном образе Playwright
(`make ui-e2e`), зависимость проекта не добавляется.

    make ui-e2e URL=http://host:8541 TEMPLATE=шаблон.pptx CONTENT=материал.md NAME=workspace
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: Сколько ждать готовой колоды, секунд. Прогон — 2–3 минуты, но у модели один слот, и чужие
#: запросы ставят его в очередь: прогон VK Tech 29.09 ждал модель 1350 с из-за общей очереди.
DEFAULT_WAIT_S = 1800

#: Надписи страницы, по которым прогон считается законченным. Берутся из `frontend/`:
#: кнопка скачивания появляется только у готовой колоды.
DONE_MARK = "Скачать"
FAILED_MARKS = ("не дошёл до конца", "Сервис отказал", "Не удалось связаться")

#: Раздел листа колоды: без него человек не видит, что стало со слайдами.
SHEET_MARK = "Лист колоды"

#: Форматы, которые обязана отдать страница (ТЗ: pptx, pdf, html).
EXPECTED_FORMATS = ("pptx", "pdf", "html")

#: Номер прогона — двенадцать шестнадцатеричных знаков: так названы и скачанные файлы.
RUN_ID = re.compile(r"\b[0-9a-f]{12}\b")


@dataclass
class Result:
    name: str
    state: str = "?"
    elapsed_s: int = 0
    run_id: str = "?"
    page_problems: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    downloads: dict[str, int] = field(default_factory=dict)

    def missing_formats(self) -> list[str]:
        """Форматы, которые страница не отдала или отдала пустыми."""
        return [
            fmt
            for fmt in EXPECTED_FORMATS
            if not any(
                name.endswith(f".{fmt}") and size > 0 for name, size in self.downloads.items()
            )
        ]

    def passed(self) -> bool:
        """Прогон через UI удался: колода готова, все форматы скачаны, ошибок страницы нет."""
        return (
            self.state == "done"
            and not self.missing_formats()
            and not self.page_problems
            and not self.console_errors
        )


def state_of(text: str) -> str | None:
    """Чем кончился прогон по тексту страницы: `done`, `failed` или ещё идёт (`None`)."""
    if DONE_MARK in text:
        return "done"
    if any(mark in text for mark in FAILED_MARKS):
        return "failed"
    return None


def run_id_of(*texts: str) -> str:
    """Номер прогона: из имён скачанных файлов, иначе со страницы, иначе «?»."""
    for text in texts:
        if found := RUN_ID.search(text):
            return found.group(0)
    return "?"


def _page_errors(page: Any) -> list[str]:
    found = []
    for selector in ('[data-testid="stException"]', '[data-testid="stAlertContentError"]'):
        for element in page.locator(selector).all():
            found.append(f"{selector}: {element.inner_text()[:400]}")
    return found


def run(
    url: str, template: Path, content: Path, out: Path, name: str, args: argparse.Namespace
) -> Result:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

    out.mkdir(parents=True, exist_ok=True)
    result = Result(name=name)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, locale="ru-RU")
        page.on(
            "console",
            lambda m: (
                result.console_errors.append(f"{m.type}: {m.text[:300]}")
                if m.type == "error"
                else None
            ),
        )
        page.on("pageerror", lambda e: result.console_errors.append(f"pageerror: {str(e)[:300]}"))
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.get_by_text("Собрать презентацию").wait_for(timeout=60000)
        page.screenshot(path=str(out / "01-start.png"), full_page=True)

        page.get_by_text("Задать", exact=True).click()
        slides = (
            page.locator('[data-testid="stNumberInput"]')
            .filter(has_text="Слайдов")
            .locator("input")
        )
        slides.fill(str(args.slides))
        slides.press("Enter")
        seed = (
            page.locator('[data-testid="stNumberInput"]').filter(has_text="Seed").locator("input")
        )
        seed.fill(str(args.seed))
        seed.press("Enter")
        page.locator('[data-testid="stSelectbox"]').filter(has_text="Профиль прогона").click()
        page.get_by_role("option").first.wait_for(timeout=15000)
        page.get_by_role("option", name=args.profile, exact=True).click()
        ask = page.locator('[data-testid="stCheckbox"]').filter(has_text="Спросить меня")
        if ask.count() and ask.locator("input").is_checked():
            ask.click()
        page.wait_for_timeout(1500)

        uploaders = page.locator('[data-testid="stFileUploader"] input[type=file]')
        uploaders.nth(0).set_input_files(str(template))
        page.wait_for_timeout(2000)
        uploaders.nth(1).set_input_files(str(content))
        page.wait_for_timeout(2000)
        page.screenshot(path=str(out / "02-filled.png"), full_page=True)
        page.get_by_role("button", name="Собрать презентацию").click()

        started = time.monotonic()
        while time.monotonic() - started < args.wait:
            page.wait_for_timeout(5000)
            result.page_problems += _page_errors(page)
            if (state := state_of(page.inner_text("body"))) is not None:
                result.state = state
                break
        result.elapsed_s = round(time.monotonic() - started)
        page.screenshot(path=str(out / "03-finished.png"), full_page=True)

        sheet = page.get_by_text(SHEET_MARK)
        if sheet.count():
            sheet.first.click()
            page.wait_for_timeout(8000)
            page.screenshot(path=str(out / "04-sheet.png"), full_page=True)
        elif result.state == "done":
            result.page_problems.append("лист колоды не найден на странице")

        for button in page.locator('[data-testid="stDownloadButton"] button').all():
            label = button.inner_text()
            try:
                with page.expect_download(timeout=60000) as info:
                    button.click()
                target = out / info.value.suggested_filename
                info.value.save_as(str(target))
                result.downloads[target.name] = target.stat().st_size
            except Exception as error:
                result.page_problems.append(
                    f"скачать {label}: {type(error).__name__} {str(error)[:200]}"
                )

        result.page_problems += _page_errors(page)
        result.page_problems = sorted(set(result.page_problems))
        result.run_id = run_id_of(*result.downloads, page.inner_text("body"))
        browser.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("url")
    parser.add_argument("template", type=Path)
    parser.add_argument("content", type=Path)
    parser.add_argument("--name", default="run")
    parser.add_argument("--out", type=Path, default=Path("artifacts/ui-e2e"))
    parser.add_argument("--profile", default="plan_b")
    parser.add_argument("--slides", type=int, default=12)
    parser.add_argument("--seed", type=int, default=1341)
    parser.add_argument("--wait", type=int, default=DEFAULT_WAIT_S)
    args = parser.parse_args(argv)

    out = args.out / args.name
    result = run(args.url, args.template, args.content, out, args.name, args)
    report = {
        **asdict(result),
        "missing_formats": result.missing_formats(),
        "passed": result.passed(),
    }
    text = json.dumps(report, ensure_ascii=False, indent=1)
    (out / "result.json").write_text(text, encoding="utf-8")
    print(text)
    return 0 if result.passed() else 1


if __name__ == "__main__":
    sys.exit(main())
