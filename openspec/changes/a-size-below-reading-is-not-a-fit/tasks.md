# Tasks — a-size-below-reading-is-not-a-fit

- [x] Тесты `tests/unit/test_a_size_below_reading.py` (красные до правки: 4 из 6, два — страховка прежнего исхода)
- [x] `layout/by_design.py`: `READING_FLOOR_PT`, `DesignRules(reading_floor_pt=…)`
- [x] `layout/fitting.py`: `_floor_of` — наибольшее из порога и пола заголовка; зона и блок по макету
- [x] Замер до/после: сборщик приёмки RG29 + `scripts/check_deck_readable.py` на трёх шаблонах
- [x] Полный pytest, ruff, mypy, lint констант, холодный шаблон
- [ ] Запросы тимлиду (порог в конфиге, пол в `_titles_yield_size`) и потоку C (`shrink_font`)
- [ ] Живой прогон на ml110 (тимлид)
