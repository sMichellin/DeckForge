# Tasks — the-writer-removes-whole-groups

- [x] База на `plan-b`: pytest, ruff, mypy, lint констант до правки
- [x] Эталон `legacy` до правки кода: XML слайда `clone_recipe` без паспорта (синтетика и VK Tech) — `tests/fixtures/the-writer-removes-whole-groups/`
- [x] Тесты `tests/unit/test_the_writer_removes_whole_groups.py`: группа с плашкой и иконкой, ряд из 4 при 2 пунктах, одиночная группа, пустое место, заголовок, фигура вне паспорта, таблица автора
- [x] `rendering/recipe_slide.py`: развилка в `clone_recipe` — перенос в ряду, удаление групп, `_drop_unfilled_frames` на обоих путях
- [x] Мерило строки 3: три колоды фикстур 28.09 без паспорта и с паспортом, PNG, счёт по группам; `deckforge audit`, `plan_b_metrics`
- [x] Холодный шаблон `tests/e2e/test_cold_template.py`
- [x] Полный pytest, ruff, mypy, lint констант, `openspec validate`
- [x] Proposal по факту, статус в «Поток B» `IMPLEMENTATION.md`
