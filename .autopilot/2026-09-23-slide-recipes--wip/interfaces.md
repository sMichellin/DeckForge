# Интерфейсы

## Правила проекта, которые исполнитель не выведет сам

- Python, пакет `src/deckforge`. Проверки — без podman, через venv вне папки проекта
  (см. память «DeckForge: проверки без podman»): pytest / ruff / mypy; гейты `make gates`.
- AGENTS.md «Нерушимое» 1–12 обязательны: ни RGB, ни имён макетов, ни номеров слайдов
  в коде; промпты только в `prompts/` через `deckforge.registry`; LLM пишет только `SlideIR`.
- Владение файлами — `docs/TEAMWORK.md` §2. Чужой файл вне зоны своего таска — стоп, `BLOCKED`.
- Новая зависимость — не ставить, вернуть `BLOCKED`.
- Код тасков 02–06 пишется только после «ок» тимлида по `openspec/changes/slide-recipes/proposal.md`.

## Границы, решённые в спецификации

## Границы и швы

| Модуль | Владеет | Выставляет | Прячет |
|---|---|---|---|
| `designsystem.recipes` | каталог рецептов шаблона | `recipes(manifest, ds) -> list[Recipe]`; `Recipe{recipe_id, example_index, part_name, kind, zones: list[Zone], repeats: int, has_picture: bool}`; `Zone{zone_id, xml_id, role: TypeLevel, repeat: int \| None, capacity_chars: int, size_pt}` | вывод вида и ролей, группировку повторов |
| `composition.recipe_picker` | выбор рецепта под слайд | `pick_recipe(slide_plan, recipes, previous: str \| None) -> Recipe \| None` | правила вместимости и чередования |
| композитор (существующий) | текст по зонам | `SlideIR` с `recipe_id` и `zone_id` у блоков | промпт |
| `rendering.recipe_slide` | копирование примера в колоду | `clone_recipe(prs, recipe, slide_ir, content) -> slide` | XML, связи, удаление повторов, подмену текста и картинки |
| writer (существующий) | колода | ветка: `recipe_id` есть → `clone_recipe`, нет → как сейчас | порядок «клонировать → удалить примеры» |

Швы для тестов: `recipes()` на манифесте (синтетическом и трёх VK), `pick_recipe()`
на планах, сквозной `write()` → открытие файла python-pptx + рендер LibreOffice.
Главный шов — `write()` с IR по рецепту: всё видимое пользователю проверяется там.


### Запросы тимлиду (контракты и чужие файлы)

| Что | Где | Зачем |
|---|---|---|
| `ExampleShape.xml_id: int` | `domain/template.py` | найти фигуру примера в XML при копировании |
| `TemplateExample.part_name: str` | `domain/template.py` | найти часть слайда-примера без опоры на порядок |
| `ExampleShape.text` не нужен — хватит `text_len` и `size_pt` | — | сознательно не просим |
| `SlideIR.recipe_id: str \| None = None` | `domain/slide.py` | writer знает, какой пример копировать |
| `zone_id: str \| None = None` у текстовых блоков | `domain/slide.py` | writer знает, в какую зону писать блок |
| заполнение `xml_id`, `part_name` | `parsing/ooxml/examples.py` (тимлид) | — |
| узел compose передаёт рецепты, отчёт — долю по рецепту | `pipeline/**` (тимлид) | — |
| клонирование и ветка рецепта | `rendering/writer.py` (поток B) | — |
| подбор рецепта, композиция по зонам | `composition/**`, `prompts/slide_composer/**` (поток A) | — |
| проверка `template.sample_text_left` | `audit/**`, `configs/audit_checks.yaml` (поток C) | — |

Все поля — с умолчанием, старые IR и манифесты читаются без миграции.

