# Tasks — a-size-below-reading-is-not-a-fit

- [x] Тесты `tests/unit/test_a_size_below_reading.py` (красные до правки: 4 из 6, два — страховка прежнего исхода)
- [x] `layout/by_design.py`: `READING_FLOOR_PT`, `DesignRules(reading_floor_pt=…)`
- [x] `layout/fitting.py`: `_floor_of` — наибольшее из порога и пола заголовка; зона и блок по макету
- [x] Дозапрос 1: пол в `fit_icon_list`, `fit_table`, `fit_smartart`, `fit_boxed`; KPI — открытый вопрос владельцу
- [x] D06: блок, который сокращение свело бы к нулю, — ступень под порогом, `below_reading`; привязка явного кегля проходит порог; тест «наибольшее из»
- [x] Дозапрос 2: привязка явного кегля — пол, перебор не пуст; D06 без ступени под порогом с переполнением
- [ ] D06: заметка в `notes` — строка в `pipeline/nodes/fit.py` (запрос 0 тимлиду)
- [x] Замер до/после: сборщик приёмки RG29 + `scripts/check_deck_readable.py` на трёх шаблонах
- [x] Полный pytest, ruff, mypy, lint констант, холодный шаблон
- [ ] Запросы тимлиду (порог в конфиге, пол в `_titles_yield_size`) и потоку C (`shrink_font`)
- [ ] Живой прогон на ml110 (тимлид)
