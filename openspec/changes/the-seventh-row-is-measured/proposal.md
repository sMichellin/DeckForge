# the-seventh-row-is-measured

План Б, мерило. Капабилити `plan-b-acceptance`, тимлид. Задача из эпика #242.

## Explore

Строка 7 таблицы приёмки — блоки ниже порога читаемости (10 pt) — стояла в мериле
прочерком: считает её `scripts/check_deck_readable.py` по готовому `.pptx`, а мерило
читало только `run.json`. План Б назвал 10 блоков на VK Tech, но свёл их руками.

## Propose

`plan_b_metrics.py` SHALL считать строку 7, когда рядом с отчётом лежит `out/deck.pptx`,
тем же `check_deck`, что и `check_deck_readable.py`, с шаблоном `in/template.pptx`, если
он есть. Блок — пара «слайд, фигура». Файла колоды нет — строка SHALL оставаться прочерком.

Вид находки вынесен в константу `check_deck_readable.BELOW_FLOOR`: мерило сводит
находки по нему, и переименование не обнулит строку молча.

## Verify

`tests/unit/test_the_seventh_row_is_measured.py`: рамка 9 pt из двух прогонов — один
блок; всё не ниже порога — ноль; нет файла — прочерк.

На прогонах 28.09 (`out/deck.pptx` и `in/template.pptx` рядом): WorkSpace 0, VK Tech **10**,
Education 0 — ровно как в `docs/agents/tasks-28-09.md`. На фикстурах — прочерк.

## Что осталось незакрытым

Строка 3 (пустые карточки) — после проверки потока C (#245).
