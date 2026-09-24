# openspec-deltas-are-the-contract

Процессный change: capability `skill-registry` в части инструментов, кода приложения
не касается. Повод — регрессия `recipe-is-not-the-models-word`: изменение контракта
прошло ревью и три PR'а, потому что контракт нигде не был записан так, чтобы
расхождение стало красным.

Статус: proposed (часть уже применена, см. «Сделано»)

## Explore

`openspec validate --changes` на `main` `077e2a5`: **0 passed, 123 failed**. Причина
одна и та же у всех 123 change'ей:

```
Change must have at least one delta. No deltas found.
```

Все change'и репозитория — это только `proposal.md`. `specs/` нет ни у одного, поэтому
механизм, ради которого OpenSpec и заведён, не работает нигде:

* `openspec validate` не может проверить ни один change — гейт всегда красный, то есть
  бесполезный;
* `openspec archive` не может обновить `openspec/specs/` — специфика остаётся там, где
  её оставили в марте, и расходится с кодом;
* «спек-первым» из `project.md` на практике выродилось в «proposal-первым»: описание
  замысла есть, проверяемого контракта нет.

Главные спеки вдобавок были структурно сломаны: все семь файлов
`openspec/specs/*/spec.md` начинались с **дельта-заголовка** `## ADDED Requirements`
вместо `## Requirements`, а `## Purpose` отсутствовал. Для парсера OpenSpec это значит,
что **все 34 требования были невидимы** — `validate`, `list` и `archive` их не видели
вовсе. Спека выглядела заполненной и при этом не существовала.

Связь с падением пяти прогонов прямая. `slide-recipes` добавил `recipe_id` и `zone_id`
в `SlideIR` — то есть изменил контракт capability `slide-composition` и capability
`pptx-writer`. Спеки этих capability обновить было нечем: у `slide-composition` спеки
нет вовсе, у `pptx-writer` она была невидима. Расхождение «поле принадлежит каталогу,
а спрашивают его у модели» осталось незаписанным — и обнаружилось на живом прогоне
через 138 секунд как `KeyError: 'b1'`.

## Propose

**Сделано этим проходом** (мелкое и механическое, ждать ревью незачем):

1. Семь главных спек починены: `## ADDED Requirements` → `## Requirements`, добавлен
   `## Purpose` по таблице capability из `project.md`. 34 требования снова видны парсеру.
2. Четыре новых change'а заведены **с дельтами**, и `openspec validate` на них зелёный:

   | Change | Дельты |
   |---|---|
   | `recipe-is-not-the-models-word` | `slide-composition`, `pptx-writer` |
   | `closing-slide-has-a-recipe` | `slide-composition` |
   | `design-system-in-the-skill-contracts` | `skill-registry` |
   | `sonar-quality-gate` | `skip_specs: true` (качество и инструменты, поведения не меняет) |

**Предлагается дальше:**

3. **Дельта или явный отказ — обязательны для нового change'а.** Change без `specs/`
   допустим только с `.openspec.yaml`, где `schema: spec-driven` и `skip_specs: true`,
   и только для правок инструментов, документации и чистого рефакторинга. Правило —
   в `AGENTS.md` и в `openspec/changes/README.md`.
4. **Гейт в CI**: `openspec validate --changes --specs` на PR. Пока 123 старых change'а
   не приведены в порядок, гейт проверяет **только затронутые PR'ом папки** — иначе он
   красный всегда и его снова перестанут читать. Скрипт берёт список изменённых путей
   из `git diff --name-only origin/main`.
5. **13 требований без сценариев** — дописать. Это уже существующее поведение,
   сценарий пишется по существующим тестам, а не выдумывается:

   | Спека | Требований | Без сценария |
   |---|---|---|
   | `template-preview-render` | 5 | 3 |
   | `layout-classification` | 5 | 2 |
   | `layout-fitting` | 5 | 2 |
   | `pptx-writer` | 5 | 2 |
   | `template-parsing` | 5 | 2 |
   | `design-system-extraction` | 4 | 1 |
   | `inference` | 5 | 1 |
   | **итого** | **34** | **13** |

   Пока они без сценариев, `openspec validate --specs` красный, и пункт 4 на спеках
   не включается. Один PR на спеку, по одному владельцу капабилити.
6. **Три capability без спеки вовсе**, хотя change'и по ним идут больше месяца:
   `slide-composition`, `deck-planning`, `audit-deterministic`. Первая появляется
   дельтами change'ей 1 и 2 этого плана; две остальные — отдельными проходами.
7. **Старые 123 change'а не переписываются.** Дельты им задним числом — это выдумывание
   контракта по памяти, хуже, чем его отсутствие. Вместо этого: применённые и проверенные
   уезжают в `archive/` как есть (с пометкой «без дельт, до перехода»), а специфика
   набирается заново — дельтами новых change'ей, по мере того как каждая capability
   открывается по существу. Решение по этому пункту — за владельцем: альтернатива
   («разобрать архив разом, одним проходом на capability») дороже и точнее.

## Verify

* `openspec validate <change> --type change` зелёный на всех четырёх новых change'ах
  (проверено: зелёный).
* `openspec validate --specs` зелёный после пункта 5.
* Гейт пункта 4 красный на попытке завести change без `specs/` и без `skip_specs`;
  зелёный на четырёх новых.
* Проверка, что механизм действительно работает: `openspec archive` на
  `recipe-is-not-the-models-word` обновляет `openspec/specs/slide-composition/spec.md`
  и `pptx-writer/spec.md` требованиями из дельт, и `validate --specs` после этого
  остаётся зелёным.

## Сделано

* `openspec/specs/*/spec.md` — семь файлов: `## Purpose` добавлен, дельта-заголовок
  заменён на `## Requirements`.
* Дельты четырёх новых change'ей, `openspec validate` на них зелёный.

## Что осталось незакрытым

* 13 требований без сценариев (пункт 5) — до них `validate --specs` красный.
* Судьба 123 старых change'ей (пункт 7) — решение владельца.
* `deck-planning` и `audit-deterministic` без спек (пункт 6).
