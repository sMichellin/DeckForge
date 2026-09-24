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
5. **13 требований без сценариев — дописаны** (решение владельца 24.09: не ждать
   владельцев капабилити). Сценарии сняты с существующих тестов, а не выдуманы;
   поведение не менялось ни в одном. `openspec validate --specs` — 7 passed, 0 failed.

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

   Откуда взят каждый сценарий:

   | Требование | Тест |
   |---|---|
   | `design-system-extraction` · цвет ссылкой на тему | `test_typography_and_grid.py::test_colour_is_mapped_to_a_theme_slot_not_stored_as_rgb`, `::test_colour_far_from_palette_falls_back_to_default` |
   | `inference` · исчерпанная квота | `inference/client.py::_QUOTA_CODES`, `test_layout_classifier.py::test_exhausted_quota_stops_further_calls` |
   | `layout-classification` · повторные вопросы | `test_layout_classifier.py::test_identical_geometry_is_asked_only_once`, `::test_signature_is_resolution_independent`, `::test_signature_ignores_names_but_notices_geometry` |
   | `layout-classification` · превью без LibreOffice | `test_layout_classifier.py::test_schematic_preview_is_a_png_of_the_right_shape`, `::test_schematic_preview_is_deterministic` |
   | `layout-fitting` · шаг строки | `test_layout_fitting.py::test_required_height_reported_at_final_size` |
   | `layout-fitting` · свободные не перекрывают | `test_layout_constraints.py::test_fixed_blocks_stay_and_free_ones_avoid_them`, `::test_free_blocks_share_the_content_area_in_equal_columns`, `::test_more_blocks_than_the_band_can_hold_is_a_layout_error` |
   | `pptx-writer` · нативные объекты | `test_native_objects.py::test_every_slide_has_editable_objects`, `::test_sample_slides_of_the_template_are_dropped`, `::test_unfilled_placeholders_are_removed`, `test_rendering_writer.py::test_slide_of_a_single_picture_is_rejected` |
   | `pptx-writer` · пропорции картинки | `test_rendering_writer.py::test_cover_crops_the_long_side_evenly`, `::test_cover_of_a_tall_image_crops_top_and_bottom`, `::test_contain_fits_inside_and_centers` |
   | `template-parsing` · каскад мастер → макет | `test_ooxml_layouts.py::test_geometry_is_inherited_from_master`, `::test_layout_geometry_overrides_master`, `::test_placeholder_without_geometry_anywhere_is_dropped` |
   | `template-parsing` · кэш по SHA-256 | `test_template_parsing.py::test_second_parse_comes_from_cache`, `::test_cache_is_invalidated_by_parser_version` |
   | `template-preview-render` · одна команда | `test_preview_render.py::test_whole_deck_is_converted_once`, `::test_deck_converts_to_one_png_per_slide` |
   | `template-preview-render` · превью по `slide_id` | `test_preview_plumbing.py::test_previews_are_keyed_by_slide_id`, `::test_page_count_mismatch_is_refused` |
   | `template-preview-render` · только нужные макеты | `test_preview_render.py::test_only_the_requested_layouts_are_rendered` |

   Двух сценариев в тестах нет дословно, и это названо честно: «LibreOffice для этого
   не нужен» держится на том, что тест проходит в образе приложения, где его нет,
   а не на отдельном утверждении; «пакет заново не разбирается» проверяется подменой
   `TemplateParser._build` на падающую заглушку.
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
* 13 требований без сценариев — дописаны по существующим тестам.
  `openspec validate --specs`: **7 passed, 0 failed** (было 0 из 7).
* Дельты четырёх новых change'ей, `openspec validate` на них зелёный.

## Что осталось незакрытым

* Судьба 123 старых change'ей (пункт 7) — решение владельца.
* `deck-planning` и `audit-deterministic` без спек (пункт 6).
* Гейт `openspec validate` в CI (пункт 4) — воркфлоу сейчас пропускает правки
  `openspec/**` и `docs/**` целиком (`paths-ignore` в `.github/workflows/ci.yml`),
  так что шаг валидации нужен либо отдельным лёгким job'ом без этого фильтра,
  либо снятием `openspec/**` из `paths-ignore`. Решение — за тимлидом: фильтр
  завели, чтобы правка документации не занимала раннер.
