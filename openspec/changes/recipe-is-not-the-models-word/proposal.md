# recipe-is-not-the-models-word

Правка changes `slide-recipes` (`compose-by-the-recipe`, `recipe-slide-in-the-writer`),
capability `slide-composition`. Рецидив класса ошибки, закрытого в
`code-owned-fields-not-asked`: **схема ответа просит то, чего от модели не ждут**.

Статус: proposed

## Explore

Пять прогонов на ml110 от 24.09 на `main` `077e2a5` — все пять упали на стадии `render`:

| Прогон | Стадия | Ошибка |
|---|---|---|
| `b5babbdac83f` | render, 138 с | `KeyError: 'b1'` |
| `98a2c58353f3` | render | `KeyError: 'b1'` |
| `dc59f95047c0` | render | `KeyError: 'b1'` |
| `edf7b44ebbb8` | render | `KeyError: 'b1'` |
| `8242966c5847` | render | `KeyError: 's10-title'` |

`DeckIR` из чекпойнтов (`~/e2e-work/artifacts/runs/<id>/checkpoint.sqlite`, канал `deck`):

```
b5babbdac83f
s01 recipe=ex014  zones=[z672]                     fit={}
...
s09 recipe=ex005  zones=[z441]                     fit={}
s10 recipe=L12_15_title_slide_closing_step_a  blocks=[b1, b2]  zones=[title, body]  fit={}

98a2c58353f3
s10 recipe=L12_15_title_closing   blocks=[b1, b2]            zones=[z1, z1]   fit={}

8242966c5847
s10 recipe=L00-A                  blocks=[s10-title, s10-body] zones=[s10, s10] fit={}
```

Каталог композиций этого шаблона (29 рецептов) выдаёт `recipe_id` вида `ex001…ex029`
и `zone_id` вида `zNNN`. Ни `L12_15_title_slide_closing_step_a`, ни `L00-A`, ни зон
`title` / `body` / `s10` в каталоге нет. Зоны у `s10` вдобавок **повторяются**
(`z1, z1`, `s10, s10`), чего каталог не даёт по построению.

Это **не каталог и не writer. Это ответ модели.** `SlideIR` — это одновременно
внутренний контракт пайплайна и `response_model` промпта `slide_composer` (`meta.yaml`).
Change `slide-recipes` добавил в `SlideIR` поле `recipe_id`, а в блоки — `zone_id`,
но не добавил их в `response_omit`:

```yaml
# prompts/slide_composer/1.3.1/meta.yaml
response_omit: [x, y, cx, cy, slide_id, layout_id, variant, provenance]
```

`scripts/gen_schemas.py` вырезает из `schema.json` только перечисленное, поэтому
`recipe_id` (строка 985) и `zone_id` (десять вхождений) остались в схеме ответа —
модель обязана их заполнить и заполняет чем придётся. `_bind` отдаёт
`ir.model_copy(update={...})` (`composition/composer.py:843`) — `recipe_id`, `zone_id`
и `fit_report` от модели проходят насквозь. `bind_to_recipe` перезаписывает их только
если рецепт **выбран**; `composer.py:424`:

```python
return bind_to_recipe(composed, recipe) if recipe is not None else composed
```

На `s10` рецепт не выбран (почему — change `closing-slide-has-a-recipe`), и выдумка
модели уезжает в `DeckIR` как факт.

**Дальше три слоя понимают «слайд по рецепту» тремя разными способами** — вот где
архитектура разъехалась, а не в самой дизайн-системе:

| Слой | Предикат | Файл |
|---|---|---|
| валидатор писателя | `slide.recipe_id and block.zone_id` | `rendering/writer.py:207` |
| вписывание | `slide.recipe_id` | `pipeline/nodes/fit.py:140` |
| писатель | `slide.recipe_id in self.recipes` | `rendering/writer.py:494` |

Сцепление и даёт падение:

1. валидатор видит `recipe_id` и `zone_id` → пропускает проверки рамки и вписывания
   (`continue`), слайд признан годным;
2. `fit` видит `recipe_id` → возвращает слайд как есть (правка `ba00290`), `fit_report`
   остаётся пустым;
3. писатель ищет `recipe_id` **в каталоге**, не находит → уходит в `_render_slide`,
   где `slide_ir.fit_report[block.block_id]` — прямое индексирование
   (`writer.py:559, 578, 591, 597, 606`) → `KeyError: 'b1'`.

Каждый слой по отдельности прав. Общего контракта «что такое слайд по рецепту» нет.

Ответ на вопрос владельца «правильно ли агент встроился»: дизайн-систему он строит
(29 рецептов, зоны, повторы, части — всё на месте) и работать в её рамках способен.
Встроился он неправильно в одном: **поля, которыми владеет каталог, он оставил в
контракте модели**. Пока схема ответа спрашивает `recipe_id` и `zone_id`, «работа по
дизайн-системе» на каждом слайде, которому каталог рецепта не дал, подменяется
галлюцинацией — и e2e падает не в дизайн-системе, а в писателе.

## Propose

Один владелец на поле, один предикат на понятие.

1. **`response_omit` пополняется** (`prompts/slide_composer/1.4.0/meta.yaml`, версия
   поднимается, `registry.yaml` → `active: 1.4.0`):
   `[x, y, cx, cy, slide_id, layout_id, variant, provenance, recipe_id, zone_id, fit_report]`.
   `make schemas` перегенерирует `schema.json`. Промпт про зоны и рецепты не говорит
   и не должен: ADR-003 — модель файла не видит.
2. **Композитор снимает эти поля с ответа явно**, не только схемой: грамматика
   llama.cpp не гарантирует отсутствие лишнего ключа, а `pattern` из схемы вырезается
   (#50). `_bind` собирает слайд с `recipe_id=None`, `fit_report={}` и блоками без
   `zone_id`. Названное моделью пишется в `notes` прогона, а не в `DeckIR`.
3. **Единый предикат** `deckforge/domain/slide.py`: `SlideIR.by_recipe` — «все блоки
   стоят в зонах рецепта и рецепт назван». Валидатор, `fit` и писатель спрашивают
   только его. Расхождение трёх условий становится невозможным.
4. **Писатель не индексирует `fit_report` напрямую.** `fit_report.get(block_id)`;
   нет записи — кегль берётся из типошкалы манифеста по роли блока, и это оговорка
   в `degradations`, а не `KeyError`. Колода из десяти слайдов лучше отсутствия колоды
   (то же решение, что в `degradation-is-not-an-error`).
5. **Инвариант на входе в writer.** `SlideValidator.problems`: `recipe_id`, которого
   нет в каталоге, — это `WriterError` с внятным текстом, а не тихий уход в
   `_render_slide`. Если пункты 1–3 сработали, эта ветка недостижима; она нужна затем,
   чтобы следующая утечка контракта называла себя, а не падала `KeyError` на стадии
   `render` после 138 секунд.

Правки 4 и 5 — страховка: они снимают падение даже если модель снова что-то придумает.
Правки 1–3 убирают причину.

## Разбивка по потокам

Правки трогают файлы четырёх владельцев, поэтому это **зонтичное предложение**, а не один
PR (правило 3 `AGENTS.md`). Дочерние change'и и порядок — [docs/agents/tasks-24-09.md](../../../docs/agents/tasks-24-09.md):

| Таск | Change | Владелец | Файлы | Приоритет |
|---|---|---|---|---|
| RG1 | `composer-does-not-name-the-recipe` | A | `composition/composer.py` | **P0, сегодня** |
| RG3 | `by-recipe-is-one-predicate` | тимлид | `domain/slide.py`, `schemas/**`, `pipeline/nodes/fit.py` | P1, первым из P1 |
| RG4 | `composer-response-schema-without-recipe` | A | `prompts/slide_composer/1.4.0/**`, `composition/composer.py` | P1, после RG3 |
| RG5 | `writer-survives-a-missing-fit` | B | `rendering/writer.py` | P1, после RG3 |
| RG7 | — (в составе RG4) | тимлид | `prompts/registry.yaml`, `schemas/**` | P1, после RG4 |

Дельты этого предложения (`specs/slide-composition/`, `specs/pptx-writer/`) — общие:
RG3 и RG4 закрывают требования по `slide-composition`, RG5 — по `pptx-writer`.

RG1 стоит отдельно и первым намеренно. Писатель на таком слайде падает не только на
`fit_report`: блок с `zone_id` не имеет `bbox`, и `_add_textbox` разложится на `None`.
Единственное место, где цепочка чинится целиком одним файлом, — вход в `_bind`.

## Verify

Красные до правки:

* `tests/unit/test_composition.py`: схема ответа `slide_composer` не содержит
  `recipe_id`, `zone_id`, `fit_report` (проверка по `bundle.response_schema`, как в
  `code-owned-fields-not-asked`);
* композитор на ответе модели с `recipe_id: "L12_15_title_closing"` и зонами
  `title`/`body` отдаёт слайд без `recipe_id` и без `zone_id`, а названное — в `notes`;
* `tests/unit/test_pipeline_fit.py`: слайд с `recipe_id`, но с блоками без `zone_id`,
  **вписывается** (не попадает под пропуск `ba00290`);
* `tests/unit/test_pptx_writer.py`: слайд с `recipe_id`, которого нет в каталоге, даёт
  `WriterError` с названием рецепта, а не `KeyError`;
* `tests/unit/test_pptx_writer.py`: блок без записи в `fit_report` пишется кеглем
  типошкалы и добавляет оговорку.

Регресс-воспроизведение без модели: `DeckIR` из чекпойнта `b5babbdac83f`
(слайды `s01…s10` как есть) прогоняется через `export_pptx` — до правки `KeyError: 'b1'`,
после правки файл пишется, `s10` идёт по макету `L12` с вписыванием, оговорка названа.

Живой прогон на ml110: тот же шаблон и тот же `task_desription.md`, что у
`b5babbdac83f`, — прогон доходит до `export`. Проверить в отчёте, что `design_system_usage`
показывает рецепт на всех десяти слайдах (после `closing-slide-has-a-recipe`) и что
`recipe` в отчёте прогона совпадает с `exNNN` из каталога.

Гейты: полный `pytest`, `ruff`, `mypy`, `make schemas` без diff,
`scripts/lint_no_template_constants.py`.

## Что осталось незакрытым

* Почему `s10` вообще остался без рецепта — отдельный change `closing-slide-has-a-recipe`.
  Без него `s10` будет собираться по макету (корректно, но мимо дизайн-системы).
* Регистрация дизайн-системы в контрактах скиллов — `design-system-in-the-skill-contracts`.
* Проверка «`recipe_id` в `DeckIR` есть в каталоге» в детерминированном аудите
  (`audit/deterministic/template.py`) — стоит добавить, но это уже capability
  `audit-deterministic`, отдельным change'ем.
