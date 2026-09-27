# Tasks — a-decoration-leaves-with-its-zone

- [x] Замер до правки: сборщик приёмки на трёх шаблонах + Education `ex013` с двумя фактами; превью до/после
- [x] Тесты писателя `tests/unit/test_a_decoration_leaves_with_its_zone.py` (красные до правки 4 из 6)
- [x] `rendering/recipe_slide.py`: `_drop_orphan_decor` — линии каскадом, плашки, иконки внутри плашки; `TOUCH_SHARE`, `LINE_SHARE`, `FULL_SPAN_SHARE`
- [x] Калибровка допуска: 1 % (2 % снимают пагинатор VK Tech `ex003`)
- [x] Проверка `template.decor_leads_nowhere` (`warning`, `params` в `configs/audit_checks.yaml`), запись в `AUDIT.md`
- [x] Тесты проверки `tests/unit/test_a_decoration_leaves_with_its_zone_audit.py` — нарушитель, норма, пропуск
- [x] Счётчики реестра: `template.*` 9 → 10, детерминированных 33 → 34
- [x] Замер проверки на колодах сборщика: до правки писателя 13 находок, после — 0
- [x] Полный pytest, ruff, mypy, lint констант, холодный шаблон, `openspec validate --strict`
- [ ] `warning` → `error` после прогона на стенде (решение владельца)
- [ ] Холодный прогон трёх колод на стенде ml110 (запрос тимлиду)
