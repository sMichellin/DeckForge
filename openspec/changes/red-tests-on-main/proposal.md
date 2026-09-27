# red-tests-on-main

Семь тестов были красными на `main` (замечено при слиянии #213–#221). Статус: implemented,
ждёт ревью (27.09). Ветка `fix/red-tests-on-main`.

## Что было и что сделано

| Тест | Причина | Исправление |
|---|---|---|
| `test_manifest_round_trips_through_json[Metropolis.pptx]` | **Ошибка кода.** `BBox` пишет вычисляемые `right`/`bottom` в JSON, а `extra="forbid"` отвергает их при чтении. Хранимый `BBox` есть только у декора (`StaticShape.bbox`), поэтому падал лишь шаблон с декором — и его манифест не читался бы ни из кэша, ни из чекпойнта | `domain/base.py`: валидатор `BBox` снимает `right`/`bottom` на входе. Вывод модели и JSON-схемы не меняются |
| три теста промптов (`test_a_block_...`, `test_a_check_...` ×2) | `read_text()` без кодировки: на Windows читается как cp1251 | `encoding="utf-8"` |
| `test_runner_populates_the_registry_itself` | подпроцесс не видит `pythonpath` из pytest и без установленного пакета падает на `import deckforge` | подпроцессу передаётся `PYTHONPATH` с `src` |
| два `test_audit_spelling` | в локальном окружении не стоял `language-tool-python`, хотя он в основных зависимостях | кода не касается: `pip install language-tool-python` (в CI ставит poetry) |

`domain/**` по правилу 11 — зона тимлида; правка сделана по поручению владельца 27.09
(«поправим ошибки»).

## Проверка

`tests/unit/test_a_stored_bbox_survives_json.py` — круг через JSON у `BBox` и `StaticShape`
без привязки к шаблону (нарушитель до правки), неверные `x`/`cx` по-прежнему отвергаются.
