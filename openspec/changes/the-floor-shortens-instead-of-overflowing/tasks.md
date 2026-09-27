# Tasks — the-floor-shortens-instead-of-overflowing

- [x] Замер до правки: сборщик приёмки на трёх шаблонах кейса + `scripts/check_deck_readable.py` (находки нет); тестовая колода VK Tech (`ex002`/`ex004`/`ex005`) — находка воспроизведена, путь (а)
- [x] Стоп по пути (а), замер вариантов 1 и 2, решение владельца D07 — вариант 2
- [x] Тесты `tests/unit/test_the_floor_shortens_instead_of_overflowing.py` (красные до правки: 3 из 5, два — страховка прежнего исхода и RG39)
- [x] `layout/fitting.py`: `_NEIGHBOUR_OVERLAP_SHARE = 0.1`, `_room_below` не считает соседом зону с перекрытием меньше доли
- [x] Замер после правки: «текст выше рамки» 0, «тексты наложились» 0 на тестовой колоде и трёх колодах сборщика
- [x] Полный pytest, ruff, mypy, lint констант, холодный шаблон
- [ ] Прогон `scripts/check_deck_readable.py` на холодном разборе VK Tech после мержа (тимлид)
