# Интерфейсы прогона

## Правила проекта, которые нельзя вывести из кода

**Проект:** DeckForge — генерация презентаций в стиле произвольного шаблона.
Python 3.12, Pydantic v2, Typer (CLI), python-pptx, pytest, ruff, mypy.

**Цикл OpenSpec (AGENTS.md):** код без принятого change-предложения не пишется.
Предложение этого прогона — `openspec/changes/design-system-page/proposal.md`,
его пишет таск 01. Остальные таски работают под ним.

**Нерушимые правила репозитория, которые связывают этот прогон:**

| # | Правило | Чем проверяется |
|---|---|---|
| 1 | Слой не импортирует слой выше себя; `domain` не знает про I/O | `tests/unit/test_architecture_boundaries.py` |
| 2 | Никаких констант конкретных шаблонов: ни RGB, ни имён гарнитур, ни EMU, ни имён макетов | `scripts/lint_no_template_constants.py` |
| 5 | Цвет — имя слота темы, не `#RRGGBB` | схема `ColorRef` |
| 6 | Кегль — только из `manifest.typography_scale` | `domain.rules.next_size_down` |
| 11 | **`src/deckforge/domain/**` и `schemas/**` не трогать вообще** — это файлы тимлида | ревью |
| — | Генерация презентаций не меняется: `composition/`, `prompts/`, `audit/`, `rendering/`, `pipeline/` — не трогать | ревью, требование R18 |

Правило 2 — главная ловушка этого прогона. Страница показывает цвета и кегли, и соблазн
вписать `#0077FF` или `16px` велик. Литеральный цвет появляется ровно в одном месте —
в блоке `:root`, который собирается из темы шаблона; вся остальная разметка ссылается
на `var(--accent1)` и подобное. Размеры — доли от величин шаблона, а не пиксели из головы.

**Команды (машина без podman, venv вне папки проекта):**

```bash
PYTHONIOENCODING=utf-8 /c/Users/gulin/.venvs/deckforge/Scripts/python.exe -m pytest -q -p no:cacheprovider
/c/Users/gulin/.venvs/deckforge/Scripts/python.exe -m ruff check src tests scripts
/c/Users/gulin/.venvs/deckforge/Scripts/python.exe -m mypy
/c/Users/gulin/.venvs/deckforge/Scripts/python.exe scripts/lint_no_template_constants.py
```

База до начала прогона: 1240 passed, 20 skipped. Пропуски требуют LibreOffice или LLM —
это норма, а не поломка.

**Шаблоны для проверок:**

- кейса: `tests/fixtures/templates/VK Tech шаблон.pptx`,
  `tests/fixtures/templates/VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx`,
  `tests/fixtures/templates/Шаблон презентации VK Education.pptx`
- холодные (система их не видела): `архив/slidewright/ЛЦТ2026 Шаблон презентации.pptx`,
  `архив/slidewright/Шаблон презентации 2024.pptx`

**Недостающая зависимость — это `BLOCKED`, а не повод её поставить.** Ничего не
устанавливать: вернуть таск со статусом и назвать, чего не хватило.

## Границы, решённые в спецификации

| Модуль | Владеет | Выставляет | Прячет |
|---|---|---|---|
| `designsystem` | производными дизайн-системы шаблона | `derive(manifest) -> DesignSystem` | расчёт площадей, отбор ролей, пороги, правила достройки |
| `export/design_system_page` | html-представлением | `render(ds) -> str` | всю вёрстку, CSS, порядок разделов |
| `cli.design_system` | сценарием «файл → файл» | команду `design-system` | чтение шаблона, запись файла |

**`designsystem` — новый слой, стоит сразу над `domain`** в `ORDER`
(`tests/unit/test_architecture_boundaries.py`). Импортирует только `domain`.
Причина отдельного слоя: на шаге 4 общего плана этими же производными будет
пользоваться `composition`, которая стоит правее, — иначе её пришлось бы тащить
в `export`.

**Шов для тестов один — `derive(manifest) -> DesignSystem`.** Всё, что выражается
числом, проверяется на нём. Рендер проверяется дымовым тестом: разделы на месте,
внешних ссылок нет, два прогона равны побайтно.

**`DesignSystem` — одна структура, а не семь.** У каждого поля есть признак
происхождения (`measured` / `derived`), из которого рендер ставит метку «измерено
в шаблоне» / «достроено системой». Признак живёт в данных, а не в разметке.

## Что построили таски

Раздел заполняется по мере сдачи тасков: сигнатуры, которые появились, и то,
на что следующим можно опираться.

## Из таска 01 — слой и структура

```
deckforge.designsystem.derive(manifest: TemplateManifest) -> DesignSystem
deckforge.designsystem.measure.measure(manifest, ds) -> DesignSystem      # наполняет таск 02
deckforge.designsystem.synth.synthesize(manifest, ds) -> DesignSystem     # наполняет таск 03
```

`Origin = MEASURED | DERIVED`. Все модели — `DomainModel`, **frozen**: дополнять
только через `ds.model_copy(update={...})`, присваивание полю не сработает.

**Формы полей заданы таском 01 и после него не меняются** — на них держится
параллельная волна: два таска пишут в разные модули, но в одну структуру.

Заполнено таском 01:

- `typography: Typography(steps[TypeStep], origin)`, где
  `TypeStep: role, size_pt, font_family, font_ref, bold, italic, line_spacing, color_ref, purpose, width_share, origin`.
  `width_share` — кегль в долях ширины слайда, по нему таск 04 рисует живой пример.
- `grid: GridSpec(width_emu, height_emu, aspect, margins, columns, gutter_emu, column_width_emu, content_width_emu, content_height_emu, spacing, origin)`
- `spacing: SpacingScale(base_emu, base_source, steps_emu, steps_in_margin, origin)`
- `bullets: BulletSpec(char, font, color_ref, margin_left_emu, indent_emu, origin)`
- `theme: ThemeInfo(slots[ThemeSlot(ref, name, color_hex)], major_font, minor_font, origin)`

Пусто — наполняет **таск 02** (`measure.py`):

- `palette_roles[PaletteRole(role: ColorRoleKind, color_hex, nearest_ref, share, seen_on, count, label, origin)]`
- `combinations[Combination(background_hex, text_hex, accent_hex, share, seen_on, origin)]`
- `contrast_pairs[ContrastPair(foreground_hex, background_hex, foreground_label, background_label, ratio, level: ContrastLevel, from_theme, is_risk, display_only, origin)]`
- `fonts_in_use[FontInUse(family, share, in_titles, in_body, origin)]`
- `number_sizes: NumberScale(large_pt, medium_pt, small_pt, origin)`
- `components[ComponentCard(kind, repeats, axis, width_share, height_share, gap_share, text_sizes_pt, fill_ref, fill_hex, seen_on, origin)]`

Пусто — наполняет **таск 03** (`synth.py`):

- `synthesized[SynthElement(group, kind, title, purpose, text, color_ref, on_color_ref, size_pt, spacing_emu, radius_emu, line_emu, origin)]`
- `assembly_rules[AssemblyRule(text, value, unit, source, origin)]`

**База прогона уточнена:** до этого прогона дерево собирало 1382 теста, а не 1240
(цифра в начале файла была старой). После таска 01 — 1385 passed, 21 skipped.

**Порог алгоритма, а не константа шаблона:** `MIN_STEP_SHARE` в `derive.py` — 0,001
ширины слайда. Нужен потому, что у холодного «Шаблон презентации 2024» наибольший общий
делитель полей равен 1 EMU; запасной шаг в этом случае — наименьшее поле.

## Из тасков 02 и 03 — чем наполнена структура

**Роли цветов** (`ColorRoleKind`): `background` — наибольшая доля площади; `dominant` —
вторая; `accent` — доля ≥ 0,001 и разброс каналов RGB ≥ 0,15; `rare` — остальное;
`tail` — свёрнутая запись «ещё N оттенков» с суммой долей. Показывается не больше
десяти записей: покрытие 95 % площади плюс добор акцентов.

**Группы достроенного** (`SynthElement.group`): `плашки`, `списки`, `элементы`,
`доступность`.

**Виды** (`SynthElement.kind`):

- плашки — `section_label`, `tag` (по одному на уникальный акцент темы),
  `badge` трёх размеров (поперечник 2 / 3 / 4 базовых шага)
- списки — `bulleted`, `numbered`, `icon` ×3 (имена lucide: `target`, `trending-up`, `shield`)
- элементы — `divider_thin`, `divider_accent`, `divider_dashed`, `divider_quote_bar`,
  `pagination` ×3 (на светлом, на доминанте, на тёмном), `header`, `footer`,
  `table_header`, `table_row_alt`, `table_delta_up`, `table_delta_down`,
  `quote`, `callout_insight`, `callout_risk`
- доступность — `meaning_beyond_colour`

**Трактовка цветовых полей:** `color_ref` — слот, которым окрашен сам элемент
(заливка, линия, знак, цифра); `on_color_ref` — слот фона, на котором элемент лежит.
Цвет текста на заливке **не хранится**: его считает `domain.rules.readable_text_ref`.
Таск 04 обязан считать его там же, а не выбирать на глаз.

**Размеры достроенного:** `spacing_emu`, `radius_emu`, `line_emu` — доли
`ds.grid.spacing.base_emu` (линии 1/8, 1/4, 1/2 шага; радиусы 1/4 и 1/2).
Кегли — только из `typography_scale` или `size_ladder_pt`.

**Правила сборки** (`assembly_rules`, до четырёх): наименьшее поле (emu), базовый шаг
(emu), карточек в ряд (шт), пунктов в теле (строк). У каждого — `source`.

**Известные слабости на 22.09, для таска 04:**

- `_role` назначает `background` и `dominant` по индексу доли, без проверки насыщенности
- при пустых `palette_roles` (шаблон без слайдов-примеров) фон и доминанта в `synth`
  падают в `LT1` / `ACCENT1` — страница должна это переживать

## Доработка таска 02 — что появилось для страницы

- **`fonts_in_use`** — по убыванию доли знаков, `MEASURED`. Гарнитура с нулём знаков
  отброшена. **На всех трёх шаблонах кейса `ds.theme.major_font` не равен
  `fonts_in_use[0].family`** — это и есть смысл раздела: тема объявляет одно,
  примеры набраны другим.
- **`number_sizes`** — крупный из старшего кегля KPI-компонента, средний и мелкий
  по шкале вниз, `MEASURED`. Без KPI-компонента — три верхних кегля шкалы и `DERIVED`.
  Ступеней меньше трёх — недостающие `None`.
- **`components`** — карточки в порядке «вид → число слайдов → площадь», `MEASURED`.
- **`combinations`** — показанных восемь плюс **свёрнутый хвост**. Хвост опознаётся
  инвариантом: единственная запись, где `text_hex is None` и `accent_hex is None`,
  идёт последней, `share` — сумма свёрнутых, `seen_on` — их слайды. Подпись «ещё N»
  страница собирает сама по `len(seen_on)`. **Подписывать хвост следует «остальные
  слайды», а не «прочие сочетания»**: на VK Education он весит 0,49, потому что
  20 слайдов из 55 — картиночные и разделители, где нет ни цвета текста, ни акцента.
- **`contrast_pairs`** — пара темы и пара с примеров с одинаковыми цветами лежат обе,
  различаются полем `from_theme`.

## Из таска 04 — страница

```
deckforge.export.design_system_page.render(ds: DesignSystem) -> str
```

Одна html-страница целиком: без внешних ссылок и без файлов рядом. Иконки инлайном.

- Цвет текста на заливке считается слотами темы и `contrast_ratio` — `readable_text_ref`
  напрямую не вызывается, потому что он принимает `TemplateManifest`, а `render`
  получает только `DesignSystem`.
- Знак или линия достроенного элемента, неразличимые на своём фоне (ниже 3:1),
  показываются читаемым слотом темы с оговоркой в подписи. **Заливки так не
  подменяются**: белая плашка на светлом фоне — правда шаблона, у неё рамка и подпись.
- Высот шапки и подвала в структуре нет: анатомия рисует поля по `grid.margins`,
  а про шапку и подвал подписывает то, что сказали synth-элементы `header` / `footer`.
- Раздел, которому не хватило данных, пустеет честно, с подписью-причиной.
