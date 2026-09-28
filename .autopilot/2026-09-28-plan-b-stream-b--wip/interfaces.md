# Интерфейсы

## Границы, решённые в спецификации

| Модуль | Владеет | Выставляет | Прячет |
|---|---|---|---|
| `rendering/recipe_slide.py` | копию примера и всё, что с ней делает писатель | `clone_recipe(prs, recipe, slide_ir, design: DesignRules \| None = None) -> slide` | перенос в ряду, удаление групп, перестроение ряда, контраст, порог — приватные функции |
| `rendering/writer.py` | выбор пути слайда и запись колоды | `PptxWriter.write(deck, out_path, content)` — сигнатура без изменений; в 5б — параметр пути сборки у конструктора (`by_example: bool = False`) | передачу `self.design` в `clone_recipe`, деградацию блоков |
| `layout/**` | вписывание и правила ДС | `fit_slide(...)`, `DesignRules` — сигнатуры без изменений; новые методы/параметры `DesignRules` и `fit_slide` — только если нужны 5а/5б, с умолчанием = прежнее поведение | — |

Швы для тестов: **`clone_recipe`** (синтетический пример python-pptx и настоящий шаблон
через `tests.case_templates.case_template`) и **`PptxWriter.write`** (колода целиком).
Новых швов не заводится.

Контракт паспорта (`designsystem/models.py`: `ExamplePassport` → `PlaceGroup` → `Place`)
**заморожен**: читать можно, править нельзя. `domain/**`, `schemas/**` — тимлида.

## Правила проекта, которые исполнитель не выведет сам

- **Прочитать до кода:** `AGENTS.md` (нерушимые правила 1–12), `docs/TEAMWORK.md` §2 (владение), §6 (DoD).
- **Владение (TEAMWORK §2), поток B:** `src/deckforge/layout/**`,
  `src/deckforge/rendering/{writer,recipe_slide,theme_binding,images,charts,tables,smartart,icons}.py`,
  `src/deckforge/export/**`; свои `tests/unit/test_<change>.py` и их фикстуры;
  `openspec/changes/<change-id>/`; раздел «Поток B» в `IMPLEMENTATION.md`.
  **Не трогать:** `rendering/{soffice,layout_deck,layout_preview}.py`, `composition/**`,
  `planning/**`, `designsystem/**`, `domain/**`, `schemas/**`, `pipeline/**`, `scripts/**`,
  `configs/*`, `tests/conftest.py`, `AGENTS.md`, `ARCHITECTURE.md`, `docs/**`, `.autopilot/`.
  Нужна правка чужого файла — **не правь**, верни `BLOCKED` с тем, что нужно и зачем.
- **Цикл OpenSpec:** `openspec/changes/<id>/{proposal.md,tasks.md,specs/<capability>/spec.md}`
  по образцу соседних changes (например `openspec/changes/a-decoration-leaves-with-its-zone/`).
  Проверка: `npx -y @fission-ai/openspec@latest validate <id>` из корня worktree
  (с `--no-install` не работает). Код без proposal не пишется: proposal и дельта — первым коммитом.
- **Нет podman/make на машине** (правило 9 обходится так — записать в proposal):
  ```
  PY=/c/Users/gulin/.venvs/deckforge/Scripts/python.exe
  PYTHONPATH=src PYTHONIOENCODING=utf-8 $PY -m pytest -q -p no:cacheprovider
  $PY -m ruff check src tests scripts
  PYTHONPATH=src $PY -m mypy
  PYTHONPATH=src $PY scripts/lint_no_template_constants.py
  ```
  `PYTHONPATH=src` обязателен: `.pth` венва указывает на `src` основного чекаута, без него
  подпроцессы импортируют чужой код. База на `plan-b` — снять прогоном до правки.
- **Шаблоны кейса** лежат в `tests/fixtures/templates/` worktree (скопированы, в `.gitignore`,
  в git не коммитить). Холодный корпус локально пуст (`cold/` — только README): по памяти,
  `.otp` из `/c/Program Files/LibreOffice/share/template/common/presnt/` → `.pptx` в
  `tests/fixtures/templates/cold/` (в `.gitignore`). Не вышло — `test_cold_template.py`
  пропускается с причиной, это пишется в proposal; CI гоняет его на PR.
- **Фикстуры прогонов 28.09:** `tests/fixtures/runs/2026-09-28/{workspace,vk-tech,education}/`,
  `from deckforge.pipeline.replay import from_fixture`; паспорт — `with_passports(run.design_system, run.manifest, FontLibrary.default())`.
  Шаблоны к ним: workspace → `VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx`,
  vk-tech → `VK Tech шаблон.pptx`, education → `Шаблон презентации VK Education.pptx`.
- **Рендер PNG:** `"/c/Program Files/LibreOffice/program/soffice.com" --headless --norestore --convert-to pdf --outdir DIR file.pptx`
  (именно `.com`, не `.exe`), затем PDF → PNG через PyMuPDF (`fitz`). Скрипты замера — в
  scratchpad `C:\Users\gulin\AppData\Local\Temp\claude\d--------------------------\4bf703e1-65c4-415e-9abe-11841bf7c93c\scratchpad\measure\`, не в репозитории.
- **Мерило плана Б:** `PYTHONPATH=src $PY scripts/plan_b_metrics.py tests/fixtures/runs/2026-09-28/*/`;
  переаудит — `deckforge audit <фикстура>` (CLI: `PYTHONPATH=src $PY -m deckforge.cli audit ...` — сверить с `cli.py`).
- **Правила кода:** никаких констант конкретных шаблонов (RGB, гарнитуры, EMU, имена макетов);
  цвет — ссылкой на тему; кегль — из шкалы/правил ДС; новая зависимость — нельзя (`BLOCKED`).
  Стиль — как в соседнем коде: docstring по-русски, объясняющий «почему», ссылки на change/RG.
- **Git:** коммиты на своей ветке, сообщения в стиле репозитория
  (`feat(rendering): … (план Б, 4)`), в конце строка
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Не пушить, не ребейзить,
  не делать merge — это делает оркестратор.
- **Правило остановки:** строка приёмки не сдвинулась — не делать вторую правку, вернуть
  `DONE_WITH_CONCERNS` с числами.

## Построено тасками

(заполняется по мере готовности тасков)
