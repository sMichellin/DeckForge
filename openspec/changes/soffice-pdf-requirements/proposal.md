# soffice-pdf-requirements

Запрос потока B из change (16). Capability: `template-preview-render`, `export-formats`.
`rendering/soffice.py` — файл change (6), то есть тимлида.

Статус: proposed → applied

## Explore

Поток B, закрывая change (16), оставил два пункта в разделе незакрытого:

> **`to_pdf` не работает на Windows**: требует ненужный `pdftoppm` и передаёт профиль
> как `file://C:\…` (LibreOffice молча не конвертирует; `Path.as_uri()` работает).

Оба подтвердились чтением кода.

**Лишнее требование.** `to_pdf` звал общий `_require()`, который проверял обе программы
сразу. Но `pdftoppm` **режет готовый pdf на страницы** и к конвертации отношения
не имеет: он нужен только в `pdf_to_pngs`. То есть экспорт в pdf отказывал на любой
машине без poppler — включая ту, где LibreOffice стоит и прекрасно справился бы.

**Профиль передавался не как URI.** `f"file://{profile}"` на POSIX случайно совпадает
с URI, а на Windows даёт `file://C:\Users\…` — это не URI, LibreOffice его игнорирует,
берёт общий профиль и **молча ничего не конвертирует**. Диагностируется тяжело: ошибки
нет, просто нет файла на выходе.

## Propose

**Требование программы предъявляет тот, кому она нужна.** Общий `_require()` разделён
на `_require_soffice()` и `_require_pdftoppm()`; `to_pdf` спрашивает только LibreOffice,
`pdf_to_pngs` — только poppler.

**Возможности разделены так же.** `available` по-прежнему значит «полный путь до png»
и требует обеих программ — на это опираются превью и классификатор макетов. Рядом
появилось `can_convert_pdf`: pptx → pdf возможен и без poppler.

**URI собирается стандартом, а не склейкой строк:** `Path(profile).as_uri()`.

### Требования

**Требование: pdf получается там, где есть LibreOffice.** Конвертация pptx → pdf
SHALL требовать только `soffice`.

- **WHEN** `pdftoppm` в системе отсутствует
- **THEN** `to_pdf` отрабатывает
- **AND** `pdf_to_pngs` поднимает `SofficeUnavailableError` с упоминанием `pdftoppm`

**Требование: профиль передаётся как URI.** Значение `-env:UserInstallation` SHALL быть
URI формата `file:///…` на любой платформе.

## Verify

Четыре теста в `tests/unit/test_preview_plumbing.py`: конвертация без `pdftoppm`,
отказ резалки без него же, разделение `available` и `can_convert_pdf`, форма URI
(`file:///` и без обратных слэшей).

Живой прогон в образе с LibreOffice: `can_convert_pdf: True`, pdf 11 922 байта,
1 страница png — путь до превью не сломан сменой URI.

893 passed, 17 skipped; ruff, mypy strict, оба гейта ТЗ.

## Что осталось незакрытым

1. **На Windows не проверено.** Обе правки делались по описанию потока B; машины
   с Windows у меня нет. Форма URI закреплена тестом, поведение LibreOffice — нет.
2. **`export_pdf` по-прежнему без превью-пути не отличает «нет LibreOffice»
   от «конвертация не удалась»** — и то и другое приходит как `SofficeUnavailableError`.
   Для отчёта прогона этого хватает, для интерфейса (change 23) может не хватить.
