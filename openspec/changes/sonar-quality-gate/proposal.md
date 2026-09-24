# sonar-quality-gate

Cross-cutting, capability не одна — правки идут по слоям. Источник: скан SonarQube
от 24.09, `sonar-report.md`.

Статус: proposed

## Explore

Quality Gate — **ERROR**. Сводка скана: 4 bugs, 7 vulnerabilities, 320 code smells,
0 security hotspots, coverage 0.0 %, дублирование 0.3 %. Reliability C, Security D,
Maintainability A.

**Область этого change'а — только deckforge.** Скан заведён под именем проекта
`llm-proxy` и захватывает файлы с префиксом `llm-proxy:src/…` — это чужой репозиторий,
и его 9 замечаний здесь не рассматриваются и не правятся. Дальше все числа — по
deckforge:

| | Всего в скане | llm-proxy (не наше) | **deckforge** |
|---|---|---|---|
| Bugs | 4 | 0 | **4** |
| Vulnerabilities | 7 | 0 | **7** |
| Code smells | 320 | 9 | **311** (137 в `src`, 174 в тестах) |

Запрос владельцу инфраструктуры: развести скан на два проекта, иначе Quality Gate
deckforge будет краснеть от чужого кода. До разведения — исключить `llm-proxy:**`
из области gate'а.

Разбор всех 322 наших замечаний по классам. Ключевое: **девять CRITICAL — ложные
срабатывания, и «исправлять» их значит внести настоящие баги.**

### Bugs (4) — все настоящие, все дешёвые

| Место | Что | Правка |
|---|---|---|
| `inference/structured.py:29` | `^\s*```(?:json)?\s*\|\s*```\s*$` — альтернация раскрывается на весь шаблон, приоритет операторов не очевиден | обернуть в `(?:…)`, поведение не меняется |
| `tests/unit/export/test_design_system_page.py:132` | `assert render(ds) == render(ds)` | это тест детерминизма; развести в `first`/`second` — и смысл читается, и правило молчит |
| `tests/unit/test_composition.py:141` | `select_chart(dataset) == select_chart(dataset)` | то же |
| `tests/unit/test_layout_classifier.py:245` | `geometry_signature(…) == geometry_signature(…)` | то же |

### Vulnerabilities (7)

| Место | Оценка | Правка |
|---|---|---|
| `audit/findings.py:31` — SHA-1 | настоящее замечание, не настоящая угроза: хэш — идентификатор находки, не защита | `hashlib.sha1(raw.encode(), usedforsecurity=False)` — заявляет назначение и снимает правило |
| `docker/Dockerfile:3`, `Dockerfile.worker:13`, `Dockerfile.libreoffice:5` — root | настоящее | непривилегированный `USER`, владение `/app` и каталогом артефактов |
| `docker/Dockerfile:18`, `Dockerfile.worker:39` — `COPY pyproject.toml poetry.lock* ./` | настоящее, но узкое: глоб ради необязательного `poetry.lock` | лок-файл в репозиторий обязательным, `COPY` без глоба |
| `registry/prompts.py:51` — `autoescape=False` | **ложное для этого места**: Jinja здесь собирает промпт для модели, не HTML; автоэкранирование поломало бы кавычки и угловые скобки в промпте. Другого шаблонизатора в `src` нет (`grep Environment(` — одно вхождение), HTML-страница дизайн-системы собирается кодом | пометить в SonarQube как safe с этим обоснованием; в коде — комментарий рядом |

### Code smells (311): 137 в `src`, 174 в тестах

| Класс | В `src` | В тестах | План |
|---|---|---|---|
| Cognitive Complexity > 15 | 58 | — | разбивать только там, где всё равно правим по существу; список файлов ниже |
| `Split this composite assertion` | — | 120 | не правим поштучно: правило отключить для `tests/**` в профиле качества |
| `Refactor this exception test` | — | 41 | то же |
| `Extract this nested conditional` | 14 | — | по ходу дела |
| `Document this HTTPException` в `responses` | 13 | — | правим: `responses=` в декораторах — это ещё и OpenAPI для UI |
| дублирование литерала | 12 | — | константы; `"design.ink_balance"` ×4 и родня — в модуль идентификаторов проверок |
| лишний `list()` | 6 | — | убрать |
| неиспользуемый параметр | 6 | — | убрать (`recipes.py:285,310`, `synth.py:670`, `planner.py:162` `no_think`, `layout_preview.py:53` ×2) |
| `async` без `await` | 4 | — | `api/queue.py` — убрать `async` или обосновать интерфейсом |
| **`identity check` всегда True/False** | **9 CRITICAL** | — | **не править — ложные** |
| регулярка с backtracking | 4 | — | настоящее, но на коротких строках; сделать линейными |
| `Merge this RUN` | 3 | — | Dockerfile — слить, заодно меньше слоёв |
| лишний класс в `except` | 2 | — | `UnidentifiedImageError` наследует `OSError` (`writer.py:327`) — убрать |

**Про девять `identity check`.** `parsing/ooxml/background.py:47,80,83,90,97`,
`parsing/ooxml/layouts.py:125,314`, `parsing/package.py:171,178` — это `node is None` /
`node is not None` над результатом `lxml` `find()`. Sonar выводит тип как не-`Optional`
и считает проверку константной. В `lxml` она **обязательна**: `find()` возвращает
`None`, когда узла нет, а пустой элемент ложен в булевом контексте — `if node:` на
существующем, но пустом узле дал бы обратный ответ. Замена `is not None` на `if node`
здесь — прямой путь к «фон шаблона не прочитан, слайд белый». Поэтому:
пометить в SonarQube как false positive с этим обоснованием, в коде не трогать.

Coverage 0.0 % — отчёт покрытия в Sonar не загружается; тесты есть (1058+ passed).
Это настройка сканера, не состояние кода.

## Propose

Четыре порции, каждая своим PR. Порядок — по отношению пользы к риску.

**П1. Bugs и vulnerabilities (4 + 7).** Правки из таблиц выше. `registry/prompts.py`
и девять `identity check` — разметка в SonarQube, а не код. Ожидаемо: Bugs 4 → 0,
Vulnerabilities 7 → 1 (обоснованно оставленная), Reliability C → A, Security D → A.

**П2. Профиль качества под тесты.** `Split this composite assertion` и
`Refactor this exception test` — 161 замечание из 311 — на тестах отключаются в
профиле. Утверждения в тестах группируются по смыслу проверки намеренно; дробить их
поштучно значит менять 174 места и ухудшить читаемость. Решение — за владельцем:
альтернатива — исключить `tests/**` из скана целиком, но тогда теряются настоящие
находки вроде `test_layout_classifier.py:302` (константное булево выражение).

**П3. Настройка покрытия и области скана.** `pytest --cov` в CI **уже есть**
(`.github/workflows/ci.yml`, шаг «ruff, mypy, gates, tests»), не хватает только
машиночитаемого отчёта: добавить `--cov-report=xml` рядом с `term-missing` и указать
`sonar.python.coverage.reportPaths` в `sonar-project.properties`. Coverage 0.0 % —
это несобранный отчёт, а не отсутствие тестов; без него Quality Gate будет ERROR
при любом состоянии кода. Тем же проходом — исключение `llm-proxy:**` из
области, чтобы гейт deckforge отвечал за deckforge.

**П4. Сложность — только вместе с содержательными правками.** Дробить 58 функций
ради метрики не стоит: часть из них — деревья разбора OOXML, где линейный проход
читается лучше пяти хелперов. Правим те, что всё равно открываем:

| Файл | Функций | Повод открыть |
|---|---|---|
| `rendering/writer.py` | 3 | `recipe-is-not-the-models-word` (`_render_slide`, `problems`) |
| `composition/composer.py` | 4 | `recipe-is-not-the-models-word` (`_bind`) |
| `pipeline/nodes/fit.py` | 2 | `recipe-is-not-the-models-word` |
| `audit/deterministic/template.py` | 7 | самый сложный файл; отдельный проход |
| `audit/deterministic/layout.py` | 4 | отдельный проход |

Остальные — по мере работы над своей capability, без отдельного change'а.

## Verify

* П1: `pytest` зелёный; `docker build` всех трёх образов; в контейнере `id` — не root,
  прогон записывает артефакты в смонтированный том; повторный скан — Bugs 0,
  Vulnerabilities ≤ 1.
* Регулярки: тесты на строки, на которых правило срабатывало, плюс замер, что разбор
  тех же входов даёт тот же результат (`extract_json`, `_ARROW`, `_YEAR`,
  `_UNIT_IN_TITLE`).
* П2: скан после правки профиля — наши smells 311 → ≈ 150.
* П3: coverage в Sonar не 0; в области скана только deckforge; порог гейта
  согласуется отдельно.
* П4: сложность правленых функций ≤ 15, поведение закрыто существующими тестами
  (их менять нельзя — иначе это не рефакторинг).

Гейты: полный `pytest`, `ruff`, `mypy`, `docker build`.

## Что осталось незакрытым

* Порог Quality Gate по покрытию — решение владельца, не техническое.
* Отключение правил в профиле качества требует прав в SonarQube: если их нет, П2
  делается иначе (исключение `tests/**` из `sonar.sources`), и это надо назвать явно.
* Разведение скана на два проекта — запрос владельцу инфраструктуры, вне этого репозитория.
