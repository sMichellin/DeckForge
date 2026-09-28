# Tasks — the-design-system-lays-out-recipe-slides

- [x] Мерило «до» (после change 4): строки 3 и 7 по трём колодам фикстур 28.09 с паспортами
- [x] Тесты `tests/unit/test_the_design_system_lays_out_recipe_slides.py`: `design` без паспорта, ряд 2 из 4, `p:grpSp`, сетка 3 + 2, порог по ступени шкалы, сверка с паспортом, цвет на норме и на нарушителе
- [x] `rendering/recipe_slide.py`: `design` в `clone_recipe`, перестроение ряда, порог, цвет; `rendering/writer.py` — передача `self.design`
- [x] `layout/by_design.py`: ступень порога и цвет текста — ответы `DesignRules`
- [x] Мерило «после»: строки 3 и 7, лист PNG; холодный шаблон
- [x] Полный pytest, ruff, mypy, lint констант, `openspec validate`
- [x] Proposal по факту, статус в «Поток B» `IMPLEMENTATION.md`
- [x] Дозапрос 1 (ревью): цвет текста не слотом ссылки; шов писателя; `p:clrMap` мастера; заметка об унаследованном цвете; `probe_size` вместо копии правила; `_frames`, `SMALL_DECOR_SHARE`; перемер строк 3 и 7
