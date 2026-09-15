# IMPLEMENTATION.md — ход реализации

Производный документ от [ARCHITECTURE.md](ARCHITECTURE.md) §14 и [PLAN.md](PLAN.md) §4.
Архитектура отвечает «как устроено», план — «кто и к какому числу», этот файл —
**«какие именно файлы и по какому критерию считаются готовыми»**.

Единица работы — OpenSpec-change. Номера в скобках совпадают с ARCHITECTURE.md §14.
Статусы: `— готово`, `◐ в работе`, `☐ не начато`.

---

## Этап 0 — каркас (15–16.09)

### (1) `bootstrap-repo` — готово

| Артефакт | Файлы |
|---|---|
| Структура репозитория §6 | весь `src/deckforge/`, `configs/`, `prompts/`, `skills/`, `tests/`, `docker/`, `scripts/` |
| Зависимости | `pyproject.toml` (Poetry, группы `dev`/`inference`/`ui`) |
| Качество | `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, ruff + mypy strict |
| Запуск без локальных установок | `Makefile`, `docker/Dockerfile`, `docker/Dockerfile.libreoffice`, `docker/compose.yaml` |
| Правила работы | `AGENTS.md` (симлинк `CLAUDE.md`), `README.md` |
| Конфиги запуска (C11) | `configs/default.yaml`, `configs/profiles/{dev,demo,final}.yaml` |

**Критерий выхода — выполнен:** `make test` зелёный, `make lint` чистый, `make gates` проходит.

### (2) `domain-models` — готово

| Артефакт | Файлы |
|---|---|
| Контракты §4 | `domain/{template,content,plan,slide,audit,variants}.py` |
| Единицы измерения | `domain/units.py` — единственное место, где разрешены числовые литералы геометрии |
| Перечисления | `domain/enums.py` — `ColorRef`/`FontRef` делают RGB-литералы невыразимыми в IR |
| Чистые правила | `domain/rules.py` — контраст WCAG, ΔE, пересечения, шкала кеглей, выбор диаграммы |
| JSON-схемы | `schemas/*.schema.json` + `scripts/gen_schemas.py` |
| Тесты | `tests/unit/test_domain_models.py`, `test_rules.py`, `tests/golden/test_schemas.py` |

**Критерий выхода — выполнен:** схемы генерируются, golden-тесты зелёные, модели иммутабельны
и запрещают лишние поля.

### Гейты ТЗ, заведённые с первого дня — готово

Не в конце, а сейчас: гейт, добавленный в конце, обнаруживает проблему тогда, когда её уже
поздно чинить.

| Гейт | Файл | Закрывает |
|---|---|---|
| Лицензии и размеры моделей | `scripts/check_licenses.py` | C1, C2 |
| Никаких констант шаблона в `src/` | `scripts/lint_no_template_constants.py` | C6 |
| Границы слоёв | `tests/unit/test_architecture_boundaries.py` | §3 |
| Промпты не в коде | тот же файл, `test_prompts_are_not_hardcoded_in_src` | C9 |
| Реестр проверок не расходится с YAML | `tests/unit/test_audit_registry.py` | §5 |
| Бюджет времени | `tests/e2e/test_time_budget.py` (skip до change 17) | C5 |
| Холодный шаблон | `tests/e2e/test_cold_template.py` (skip до change 16) | C6 |

### (9) `skill-registry` — готово (A9, срок был 20.09)

Сделано авансом, потому что все последующие changes обращаются к промптам через реестр:
если реестра нет, промпты успевают расползтись по коду.

| Артефакт | Файлы |
|---|---|
| Промпты по версиям | `prompts/{deck_planner,slide_composer,headline_writer,visual_selector,audit_judge}/1.0.0/` |
| Реестр версий и пинов по профилям | `prompts/registry.yaml` |
| Конфиги шагов воркфлоу | `skills/{template_analyst,deck_architect,slide_designer,quality_auditor}/1.0.0/skill.yaml` |
| Загрузка | `registry/{prompts,skills,models,variants,checks}.py` |
| Тесты | `tests/unit/test_registries.py` |

### (20) `layout-variants` — объявлены, реализация с change (11)

`configs/variants.yaml` с осями различий и обоснованием каждой (требование ТЗ);
`domain/variants.py`; тест `test_three_variant_profiles_are_distinct` проверяет, что варианты
различаются по объявленным осям, а не только по названию.

---

## Этап 1 — понимание шаблона (16–17.09)

### (3) `template-parsing-core` ☐ — P2, 16.09

Файлы: `parsing/template.py`, `parsing/ooxml/layouts.py`, `parsing/ooxml/decor.py`,
`parsing/capacity.py`.

- `TemplateParser.parse()` собирает манифест; `template_id_of()` уже реализован.
- Плейсхолдеры — с каскадом `slideMaster → slideLayout`: значение макета перекрывает мастер.
- `capacity` **вычисляется** из метрик шрифта и площади, не задаётся константами.
- Кэш по SHA-256: повторный парсинг того же файла — 0 с.

**Критерий выхода:** манифест снимается с трёх шаблонов организаторов; golden-снапшоты
в `tests/golden/snapshots/`.

### (4) `theme-extraction` ☐ — P2, 16.09

Файлы: `parsing/ooxml/theme.py`, `parsing/typography.py`, `parsing/grid.py`.

- 12 цветов `clrScheme` и гарнитуры `fontScheme` — прямым разбором `theme1.xml` через lxml
  (python-pptx тему целиком не отдаёт). Ни один ключ не пустой — иначе это ошибка парсера,
  а не значение по умолчанию.
- Типошкала выводится из `lvl1pPr…lvl9pPr` и `defRPr`.
- Направляющие — из XML мастера; если их нет, **выводятся** кластеризацией координат
  плейсхолдеров, а не берутся «типовые».

**Критерий выхода:** `grid.guides_*` заполнен для всех трёх шаблонов; `guides_source`
честно говорит, откуда они взялись.

### (5) `layout-classification` ☐ — P2, 17.09

Файл: `parsing/layout_kind.py`. Эвристика по составу и геометрии плейсхолдеров, VLM —
только на спорных случаях с низкой уверенностью. Никаких списков имён макетов (C6).

**Критерий выхода:** на холодном шаблоне ≥ 80 % макетов классифицированы верно (ручная сверка).

### (6) `template-preview-render` ☐ — P4, 15.09 (образ) → 18.09 (в пайплайне)

Файлы: `audit/preview.py`, `docker/Dockerfile.libreoffice` (написан).

**Критерий выхода:** рендер кириллической строки совпадает с эталоном. Это не формальность:
без кириллических шрифтов в образе LibreOffice подменит гарнитуру, и весь VLM-аудит будет врать.

---

## Этап 2 — минимальная генерация (17–20.09)

### (7) `content-ingestion` ☐ — P1, 17.09

Файл: `parsing/content.py`. markitdown → нормализованный markdown → факты, датасеты, ассеты.
`extract_numbers()` работает по-русски: «37,5 %», «1 200 млн ₽», «x2.3».

**Критерий выхода:** каждое число из контента получило `fact_id` — без этого фактчекинг
в аудите не на что опереть.

### (8) `inference-client` ☐ — P3, 16.09

Файлы: `inference/{client,structured,vlm,t2i,cache}.py`.

- Guided decoding по `schemas/*.schema.json`: модель не может вернуть невалидный `SlideIR`.
- Prefix caching: манифест в общем префиксе сообщений — иначе параллельная композиция
  не уложится в 100 с.
- 2 ретрая, затем деградация до упрощённого макета.

**Критерий выхода:** валидный `SlideIR` в 100/100 прогонов на синтетике.

### (10) `deck-planning` ☐ — P3, 18.09

Файлы: `planning/planner.py`, `planning/narrative.py`; промпт `deck_planner@1.0.0` готов.

**Критерий выхода:** `DeckPlan` на 12 слайдов, заголовки — выводы, а не темы.
Требование заложено в промпт, а не чинится авто-фиксом после.

### (11) `slide-composition` ☐ — P3, 18.09

Файлы: `composition/{composer,layout_picker,visual_selector}.py`;
промпт `slide_composer@1.0.0` готов.

**Критерий выхода:** `SlideIR` проходит валидацию схемы; выбранный макет всегда из манифеста;
при нехватке места — деградация на более простой макет **того же шаблона**.

### (12) `layout-fitting` ☐ — P4, 17.09

Файлы: `layout/{metrics,fitting,constraints}.py`.

Порядок деградации: как есть → ступень кегля вниз по шкале шаблона → сокращение текста →
деление слайда надвое. Заголовок не уменьшается никогда.

**Критерий выхода:** текст на 500 знаков в узкий плейсхолдер → overflow пойман **до** записи
файла, а не аудитом после.

### (13) `pptx-writer` ☐ — P4, 16→18.09. **Здесь первый end-to-end**

Файлы: `rendering/{writer,theme_binding,images}.py`.

**Критерий выхода:** колода из 12 слайдов открывается в PowerPoint, все объекты нативные,
цвета меняются вместе со сменой шаблона без единой правки кода.

---

## Этап 3 — визуализации и аудит (19–22.09)

### (14) `native-charts-tables` ☐ — P4, 19.09
`rendering/{charts,tables}.py`. Серии красятся в accent-цвета **темы**.
**Критерий:** диаграмма меняет палитру при смене шаблона без правки кода.

### (15) `audit-deterministic` ☐ — P4, 20–21.09
`audit/deterministic/{layout,template,density,integrity}.py` (каркас с 24 зарегистрированными
проверками готов), `audit/runner.py`.
**Критерий:** все 24 проверки работают, у каждой тест на нарушителе и на норме.

### (16) `export-pptx-pdf` ☐ — P4, 22.09
`export/{pptx,pdf}.py`. Здесь же включается `tests/e2e/test_cold_template.py`.

### (17) `pipeline-orchestration` ☐ — P1, 19.09
`pipeline/{graph,state,budget}.py`, `pipeline/nodes/*.py` (девять узлов заготовлены).
Состояние с редьюсером для параллельной композиции уже написано.
**Критерий:** end-to-end одной командой CLI; `test_time_budget.py` включается и держит p95 ≤ 300 с.

---

## Этап 4 — полнота ТЗ (21–24.09)

| # | Change | Файлы | Критерий выхода |
|---|---|---|---|
| (18) | `audit-semantic` ☐ | `audit/semantic/{judge,grounding,spelling}.py` (11 проверок зарегистрированы) | вердикты стабильны на 3 прогонах в ≥ 80 % случаев |
| (19) | `audit-remediation` ☐ | `audit/fixes/apply.py`, узел `hitl` | пользователь видит находки и выбирает, что чинить |
| (20) | `layout-variants` ◐ | `configs/variants.yaml` готов; реализация в (11) | три колоды визуально различимы, все проходят аудит шаблона |
| (21) | `smartart-icons` ☐ | `rendering/{smartart,icons}.py`, `assets/icons/` | компоненты нативные и редактируемые поэлементно |
| (22) | `export-html` ☐ | `export/html.py` | три формата визуально совпадают |
| (23) | `service-api` + `web-ui` ☐ | `api/{app,schemas,worker}.py`, `frontend/app.py` | полный путь мышью, без CLI |

---

## Этап 5 — «со звёздочкой»

| # | Change | Условие |
|---|---|---|
| (24) | `image-generation` ☐ | только после гейта 2; первый кандидат на дескоуп |
| (25) | `codegen-fallback` ☐ | только если сработает условие пересмотра ADR-001: рендерер не покрывает > 20 % макетов холодного шаблона |

---

## Артефакты сдачи (25–28.09)

| Артефакт | Файл / скрипт | Состояние |
|---|---|---|
| A5 `README.md` | `README.md` | каркас готов, раздел «Ограничения» пополняется по ходу |
| A6 `ARCHITECTURE.md` | `ARCHITECTURE.md` | готов |
| A7 `MODELS.md` | `MODELS.md` | готов, синхронизирован с `configs/models.yaml` через CI |
| A8 `AUDIT.md` | `AUDIT.md` | готов, синхронизирован с `configs/audit_checks.yaml` через тест |
| A9 промпты отдельными файлами | `prompts/`, `skills/` | готово |
| A3 девять презентаций | `scripts/generate_submission_decks.py` | ☐ 26.09 |
| A10 питч-колода, слайды 7–11 нетронуты | `scripts/check_pitch_deck.py` | ☐ 26.09 |
| A11 воспроизводимый запуск | `configs/profiles/final.yaml` + `make up` | ◐ |
| A4 видео-демо | — | ☐ 27.09, профиль `demo` |

---

## Порядок работы с этим файлом

Статус меняется **в том же PR**, что и код. Отдельного трекера нет: доска — это
`openspec/changes/` плюс эта таблица. Change без обновлённого статуса здесь считается незакрытым.
