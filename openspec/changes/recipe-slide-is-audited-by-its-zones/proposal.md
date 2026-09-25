# recipe-slide-is-audited-by-its-zones

Правка change (15) `audit-deterministic`. Capability: `audit-deterministic`. Поток C.
Статус: proposed (тимлид, 25.09). Таск RG27.
Файлы: `audit/deterministic/template.py`, `audit/deterministic/layout.py`.

## Explore

Три прогона 24.09 на `3f9cb79` завершились `done`, и в каждом аудит дал ошибки:
13 (VK WorkSpace), 24 (VK Tech), 26 (VK Education) — **63 ошибки на три колоды**.
Разбор по проверкам:

| Проверка | WorkSpace | VK Tech | Education | Всего |
|---|---|---|---|---|
| `template.layout_not_from_template` | 7 | 10 | 10 | **27** |
| `layout.text_overflow` | 3 | 7 | 6 | **16** |
| `integrity.content_lost` | 3 | 4 | 3 | 10 |
| `integrity.empty_slide` | — | 3 | 3 | 6 |
| `template.sample_text_left` | — | — | 2 | 2 |
| `layout.image_aspect_distorted` | — | — | 2 | 2 |

Первые две — 43 ошибки из 63 — меряют слайд по рецепту **линейкой макета**, которым
этот слайд не собран.

**`layout_not_from_template`** (`template.py`) сверяет часть макета из плана с частью
макета в файле:

```python
declared = layout_of(slide, ctx.manifest)
actual = parts_in_file[number]
if declared is None or declared.part_name.lstrip("/") == actual:
    continue
```

Слайд по рецепту — копия слайда-примера, и лежит он на макете **примера**
(`Recipe.part_name`), а не на том, что выбрал `layout_picker`. Расхождение здесь —
не дефект, а устройство рецепта. В прогоне `d541b632ff97` `recipe_share` = 1.0:
все десять слайдов собраны по каталогу, и проверка срабатывает на семи из десяти.

**`text_overflow`** (`layout.py`) верит измерению, когда оно есть, и падает на оценку
по макету, когда его нет:

```python
measured = slide.fit_report.get(block.block_id)
if measured is not None: ...; continue
limit = layout.capacity.max_chars_title if block.role is TextRole.TITLE
        else layout.capacity.max_chars_body
```

У слайда по рецепту `fit_report` пуст **намеренно**: `bind_to_recipe` ставит
`fit_report={}`, а узел `fit` такой слайд пропускает (`if slide.by_recipe: return`,
change `by-recipe-is-one-predicate`). Значит проверка всегда уходит в ветку
`capacity` и меряет текст вместимостью макета, тогда как рамка у блока — зона
рецепта, и текст в неё уже обрезан по `Zone.capacity_chars`. Отсюда сообщения вида
«Текст блока b01: 42 знаков при вместимости макета 32» на слайде, где ничего
не переполнено.

Ни одна из двух проверок не обращается к `SlideIR.by_recipe`: `grep -n "by_recipe\|recipe_id"
src/deckforge/audit/deterministic/` не находит ничего.

Следствие для сдачи: число ошибок в отчёте ни о чём не говорит. Владелец видит
«26 ошибок» на колоде, где настоящих дефектов шесть, и не может отличить колоду,
которую можно отдать, от колоды, которую нельзя.

## Propose

1. **`layout_not_from_template` сверяет слайд по рецепту с частью его рецепта.**
   Не «пропускает» — именно сверяет: у слайда по рецепту объявленная часть —
   `Recipe.part_name` того рецепта, который назвал `design_system_usage`. Совпало —
   молчит; не совпало — ошибка остаётся, и она настоящая: писатель склонировал не тот
   пример. Рецепт без `part_name` (каталог до `recipes-in-the-design-system`) проверку
   пропускает: сверять не с чем, а гадать хуже, чем промолчать.
2. **`text_overflow` меряет слайд по рецепту вместимостью зоны.** Для блока
   с `zone_id` предел — `Zone.capacity_chars` той зоны, а не
   `layout.capacity.max_chars_*`. Пустой `fit_report` у такого слайда перестаёт
   означать «замера не было»: замер сделал каталог, и он в зоне.
3. **Оценка по макету остаётся ошибкой там, где она уместна** — на слайде не по
   рецепту. Ни одна проверка не смягчается, severity не понижается: снимается только
   подмена линейки.

Обе правки — про `SlideIR.by_recipe`, тот же предикат, что у узла `fit`, писателя
и html (change `by-recipe-is-one-predicate`). Четвёртый потребитель предиката,
а не четвёртое определение.

## Verify

* `tests/unit/test_audit_recipe_slide.py` (красные до правки): слайд по рецепту, чей
  `part_name` совпал с файлом, — находок нет; не совпал — находка есть; рецепт без
  `part_name` — находок нет; слайд не по рецепту — прежнее поведение.
* `text_overflow`: блок в зоне, текст короче `capacity_chars`, — молчит; длиннее —
  ошибка с упоминанием зоны, а не макета; блок без `zone_id` на том же слайде —
  прежняя ветка; слайд с непустым `fit_report` — по-прежнему верит измерению.
* Правило 7 AGENTS.md: у каждой изменённой проверки есть тест-нарушитель и тест-норма.
* Замер на трёх скачанных прогонах (`output/runs/2026-09-24-rg26-3f9cb79`):
  прогнать аудит по чекпойнтам до и после, выписать число ошибок. Ожидание —
  13 → 6, 24 → 14, 26 → 16. Расхождение с ожиданием разбирается до слияния:
  оно означает, что ложных находок было меньше или больше, чем показал разбор.

Гейты: полный `pytest`, `ruff`, `mypy`, `openspec validate recipe-slide-is-audited-by-its-zones`.

## Чего эта правка не делает

Не трогает `integrity.content_lost` и `integrity.empty_slide` — они настоящие,
причина в `bind_to_recipe`, и она правится отдельно
(`a-zone-less-block-is-not-dropped`, поток A). Не трогает `duplicate_slides`:
повтор одного рецепта подряд — вопрос подбора, не проверки.
