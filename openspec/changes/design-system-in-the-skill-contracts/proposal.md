# design-system-in-the-skill-contracts

Capability `skill-registry` (C9, ARCHITECTURE §9.1). Ответ на вопрос владельца
«правильно ли четвёртый агент встроился в архитектуру» — в части регистрации.

Статус: proposed

## Explore

Скиллы — это объявленные контракты шагов графа: «промпт отвечает, что сказать модели,
скилл — как этот шаг встроен в граф» (`skills/registry.yaml`). Четыре агента:

| Скилл | `inputs` | `outputs` |
|---|---|---|
| `template_analyst` | `[template_path]` | `[manifest]` |
| `deck_architect` | `[content, manifest, variant, seed]` | `[plan]` |
| `slide_designer` | `[slide_plan, layout, content, variant, seed]` | `[slide_ir]` |
| `quality_auditor` | `[slide_preview, content]` | `[findings]` |

**Дизайн-системы в контрактах нет нигде.** А в коде она есть у всех:

* `pipeline/nodes/parse.py:56,73` — `template_analyst` фактически отдаёт
  `(manifest, design_system)` и кладёт `design_system` в состояние графа;
* `pipeline/nodes/plan.py:182` — `deck_architect` её читает
  (change `plan-by-the-design-system`);
* `pipeline/nodes/compose.py:74` — `slide_designer` её читает
  (changes `compose-by-the-design-system`, `compose-by-the-recipe`);
* `pipeline/nodes/fit.py:420`, `pipeline/nodes/render.py:99` — вписывание и рендер
  тоже (DG2, DG3).

Каталог композиций (`design_system.recipes`) — самая свежая и самая влиятельная её
часть: по нему writer **копирует слайд-пример вместо сборки на пустом макете**. В
контрактах скиллов о нём нет ни слова.

Отсюда и разъезд, который положил пять прогонов. Когда контракт шага объявлен только
кодом, у полей нет владельца: `slide_designer` объявляет `outputs: [slide_ir]`, а
`slide_ir` с некоторого момента несёт `recipe_id` и `zone_id`, которые придумывает не
он, а `template_analyst`. Проверить это расхождение было нечем — ни `openspec/verify`,
ни тестом, потому что в реестре его не видно. Разбор падения — в
`recipe-is-not-the-models-word`.

Дизайн-система работает. Не работает **место, где написано, кто её отдаёт и кто её
получает**, — и поэтому её нарушения не видны ни на ревью, ни на гейтах.

## Propose

1. **`template_analyst` объявляет второй выход**: `outputs: [manifest, design_system]`,
   описание дополняется каталогом композиций. Версия скилла → `1.1.0`,
   `skills/registry.yaml` → `active: 1.1.0`.
2. **`deck_architect` и `slide_designer` объявляют вход** `design_system`.
   Версии → `1.1.0`. У `slide_designer` в описание добавляется, что рецепт слайду
   выбирает код (`pick_recipe`), а не модель: «вид выбирает план, конкретный пример —
   счёт» (решение §4 `slide-recipes`).
3. **Поля с владельцем.** В `skill.yaml` появляется `owns` — поля `SlideIR` и
   `TemplateManifest`, которые этот шаг заполняет. `recipe_id` и `zone_id` принадлежат
   каталогу (`template_analyst` → код композиции), не модели. Это то объявление, которого
   не хватало, чтобы `slide-recipes` заметил утечку в схему ответа.
4. **Гейт.** `scripts/lint_skill_contracts.py`: для каждого скилла с `prompt_ref`
   пересечение `owns` и полей схемы ответа промпта (`response_schema` после
   `response_omit`) обязано быть пустым. Скрипт в `make lint`. Это превращает разъезд
   контракта из «замечено на живом прогоне через 138 секунд» в «красный гейт на PR».
5. **ARCHITECTURE.md §9.1**: таблица четырёх агентов с их входами, выходами и
   владением полями — один экран, чтобы пятый агент встраивался по ней, а не по коду
   узлов.

## Verify

* `tests/unit/test_skill_registry.py`: у всех скиллов `inputs`/`outputs`/`owns`
  валидируются схемой; `template_analyst` отдаёт `design_system`; `slide_designer`
  и `deck_architect` его принимают.
* `scripts/lint_skill_contracts.py` красный на текущем `main` (`slide_composer`
  спрашивает `recipe_id` и `zone_id`, которыми владеет каталог) и зелёный после
  `recipe-is-not-the-models-word`. Это и есть доказательство, что гейт ловит именно
  тот дефект, который прошёл на e2e.
* Тест соответствия объявления и кода: поля, названные в `outputs` скилла, реально
  появляются в состоянии графа после соответствующего узла
  (`tests/integration/test_design_system_in_the_pipeline.py` дополняется).

Гейты: полный `pytest`, `ruff`, `mypy`, `make lint`.

## Что осталось незакрытым

* `owns` покрывает `SlideIR` и `TemplateManifest`. Для `DeckPlan` и `Finding`
  владение полями не расписывается — отдельным проходом, если гейт себя оправдает.
