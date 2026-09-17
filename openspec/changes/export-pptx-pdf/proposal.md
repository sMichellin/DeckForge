# export-pptx-pdf

Change (16) из ARCHITECTURE.md §14. Capability: `export-formats`. Поток B.

Статус: proposed → applied

## Explore

* `.pptx` уже пишет `PptxWriter` (13, 14): экспорт — тонкий адаптер, контент не пересобирается (C4).
* `.pdf` — тем же LibreOffice, что и превью (`rendering.soffice.SofficeRenderer.to_pdf`, §12).
  На машине разработчика (Windows, LibreOffice 26.8) `to_pdf` **не работает** по двум причинам,
  обе в `rendering/soffice.py` (файл тимлида, change 6):
  1. `_require()` требует `pdftoppm`, хотя для pdf он не нужен — только для `pdf_to_pngs`;
  2. профиль передаётся как `file://{путь}`. На Windows это `file://C:\Users\…` — невалидный адрес,
     LibreOffice молча не создаёт pdf. Проверено вручную на одной колоде: `file://C:\…` — pdf нет,
     `Path(profile).as_uri()` (`file:///C:/…`) — pdf за 6,8 с. На Linux `as_uri()` даёт тот же
     `file:///tmp/…`, что и сейчас.
  В образе воркера (Linux, poppler есть) обе проблемы не проявляются.
* Холодный шаблон: `tests/fixtures/templates/cold/` пуст (только README) — e2e-тест обязан
  пропускаться, а не падать, и включаться сам, как только туда положат незнакомый шаблон.

## Propose

* `export/pptx.py` — `export_pptx(deck, manifest, template_path, out, content=None, fonts=None)`:
  `PptxWriter.write`, затем повторное открытие файла python-pptx — битый файл не отдаётся.
* `export/pdf.py` — `export_pdf(pptx_path, out, renderer=None)`: `SofficeRenderer.to_pdf` во временный
  каталог и перенос в `out`. Рендерер подменяется в тестах; ошибка LibreOffice пробрасывается как
  `ExportError` с причиной.
* `tests/e2e/test_cold_template.py` — для каждого шаблона из `cold/`: манифест → детерминированная
  колода (заголовок и текст в плейсхолдеры каждого подходящего макета) → `fit_slide` → pptx →
  все слайды нативные; pdf — если LibreOffice доступен. Нет шаблонов — пропуск с причиной.

## Запросы тимлиду

1. `rendering/soffice.py`: `to_pdf` не должен требовать `pdftoppm`.
2. `rendering/soffice.py`: `-env:UserInstallation={Path(profile).as_uri()}` вместо `file://{profile}`.

## Apply

Реализовано: `export/{pptx,pdf}.py`, `tests/e2e/test_cold_template.py` включён.

* `export_pptx` после записи открывает файл python-pptx и не отдаёт битый: файл удаляется,
  поднимается `ExportError`.
* `export_pdf` конвертирует во временный каталог и переносит pdf ровно в `out`; ошибка
  LibreOffice — `ExportError` с причиной, частичного файла не остаётся.
* Тест холодного шаблона собирает колоду без композиции: заголовок и текст в плейсхолдеры
  макетов, не влезшие блоки убираются. Пустой `cold/` — пропуск с причиной.

## Verify

* Тесты: `tests/unit/test_export_formats.py` (подделка рендерера), `tests/integration/test_export_pptx.py`,
  `tests/e2e/test_cold_template.py`. Весь набор зелёный, ruff и mypy чистые, гейт C6 проходит.
* **pdf на Windows** — через `export_pdf` с рендерером, где профиль передан как `Path.as_uri()`:
  колоды из change (14) на VK Tech и VK Education — по 6 страниц, 156 и 93 КБ, ~10 с каждая.
  Через штатный `SofficeRenderer` на этой машине pdf не получается — см. «Запросы тимлиду».
* **Механика теста холодного шаблона** прогнана на VK WorkSpace (шаблон известный, холодной
  проверкой не считается): 12 слайдов, файл открывается.

## Что осталось незакрытым

1. **Холодного шаблона нет.** `tests/fixtures/templates/cold/` пуст — критерий C6 проверить нечем.
   Нужен шаблон, которого команда не открывала.
2. **`SofficeRenderer.to_pdf` не работает на Windows** (запросы 1 и 2 тимлиду). В образе воркера
   проблема не проявляется, но проверить это в образе не удалось: podman на машине разработчика нет.
3. **pdf не сверялся с PowerPoint построчно**: LibreOffice подменяет Play (в образе — DejaVu Sans),
   поэтому pdf визуально шире PowerPoint. Расчёт вписывания это учитывает (change 12).
4. **Ветка собрана поверх (12)–(14)**: PR откроется после их мержа.

## Archive

После мержа и зелёного CI.
