# Tasks — no-example-goes-by-design

- [x] Разведка: где на слайде без примера блок снимается или сплющивается (писатель, вписывание, узел `fit`)
- [x] Мерило «до» строк 5 и 9 на трёх шаблонах кейса без слайдов-примеров
- [ ] Эталон XML слайдов колоды без рецептов при `by_example=False` — до правки кода
- [ ] Тесты `tests/unit/test_no_example_goes_by_design.py` на подделке `RecipeAssignment` (красные до правки)
- [ ] `layout/diagram.py`: раскладка `hierarchy` и `pyramid`, `NATIVE_PATTERNS`
- [ ] `layout/fitting.py`: `fit_slide(..., by_example=False)`
- [ ] `rendering/writer.py`: `PptxWriter(..., by_example=False)`, деградация и проверка без сплющивания
- [ ] Мерило «после», холодный шаблон, полный pytest, ruff, mypy, lint констант
- [ ] Proposal по факту, статус в «Поток B» `IMPLEMENTATION.md`
- [ ] Передать `by_example=True` в `pipeline/**`, узел `fit` без сплющивания (запрос тимлиду)
