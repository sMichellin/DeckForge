# 06b — Аудит: текст шаблона остался на слайде (`template.sample_text_left`)

**Требования:** R14 (история 9), R22i (холодный шаблон)
**Blocked by:** 04 (смержен, PR #163 и раньше)
**Change:** `sample-text-left-audit` · capability `audit-deterministic` · поток C
**Ветка:** `feat/sample-text-left-audit` (уже создана от свежего `origin/main`)
**Зона (пишешь только сюда):** `src/deckforge/audit/**` (кроме `audit/preview.py`),
`configs/audit_checks.yaml`, `AUDIT.md`, `tests/unit/test_<тема>.py` (новый файл своего change),
`openspec/changes/sample-text-left-audit/proposal.md` (новый), раздел «Поток C» в `IMPLEMENTATION.md`.
**Не трогать:** `domain/**`, `schemas/**`, `rendering/**`, `pipeline/**`, `parsing/**`,
`tests/conftest.py`, `scripts/**` — чужие (docs/TEAMWORK.md §2). Нужна правка там — `BLOCKED`
с тем, что именно и зачем.

## Что должно заработать

Аудит колоды находит слайд, собранный по рецепту (копия слайда-примера шаблона), на котором
осталась фигура с исходным текстом примера, и выдаёт находку `template.sample_text_left`
с указанием слайда и фигуры. Если все зоны заменены нашим текстом или удалены — находки нет.

## Из брифа, дословно

> «давай а» — и заменяет в нём текст

## Из спецификации

`spec.md`, история 9: «После записи ни одна фигура слайда по рецепту не содержит исходного
текста примера. Проверка аудита `template.sample_text_left` (нарушитель и норма)».
Зонтичное предложение `openspec/changes/slide-recipes/proposal.md`, раздел «Требования» →
«Требование: текста шаблона в колоде нет — `template.sample_text_left`».

## Что известно о соседях (прочитай код, а не верь пересказу)

- Контекст проверки — `audit/context.py` (`AuditContext`: `manifest`, `deck`, `deck_path`, …).
  Похожие проверки по готовому файлу — `audit/deterministic/template.py`, `integrity.py`
  (`integrity.placeholder_text`, `layout.image_aspect_distorted` читают `.pptx`).
- Слайд по рецепту: `SlideIR.recipe_id`, блоки с `zone_id`; каталог — `designsystem/recipes.py`;
  копирование — `rendering/recipe_slide.py` (как сохраняются `cNvPr id` фигур примера).
- В манифесте текста примера нет **сознательно** (`ExampleShape.text` не просили): есть
  `xml_id`, `text_len`, `TemplateExample.part_name`, и у манифеста есть путь/источник шаблона.
  Как узнать исходный текст — реши сам по коду; вариант «открыть сам шаблон и сравнить с фигурой
  примера по `part_name` + `xml_id`» допустим. Нельзя: зашивать тексты, имена макетов,
  номера слайдов конкретных шаблонов (AGENTS.md, правило 2; `scripts/lint_no_template_constants.py`).
- Нечего проверять (нет `deck_path`, нет шаблона, ни одного слайда по рецепту, холодный
  шаблон без примеров) — по правилам слоя: `CheckUnavailable` / пропуск, а не «прошла»,
  и не падение. Посмотри, как это сделано у соседей, и повтори.

## Критерии приёмки

- [ ] проверка `template.sample_text_left` зарегистрирована в `configs/audit_checks.yaml`
      (deterministic, severity — обоснуй в proposal) и описана в `AUDIT.md`
- [ ] тест на нарушителе: слайд по рецепту с оставшимся текстом примера → находка на этом слайде
- [ ] тест на норме: текст зон заменён / зоны удалены → находки нет
- [ ] слайд без `recipe_id` и холодный шаблон — не ложная находка и не исключение (тест)
- [ ] `test_declared_checks_are_implemented` и остальные тесты аудита зелёные
- [ ] `openspec/changes/sample-text-left-audit/proposal.md` по факту: что выяснилось, что решено,
      что осталось незакрытым; статус в разделе «Поток C» `IMPLEMENTATION.md`
- [ ] полный набор: pytest, ruff, mypy, `scripts/lint_no_template_constants.py` — чисто
