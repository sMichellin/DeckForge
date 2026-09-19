# code-owned-fields-not-asked

Правка changes (8) `inference-client`, (10) `deck-planning`, (11) `slide-composition`.
Выполнена тимлидом за поток A по решению владельца проекта.

Статус: proposed → applied

## Explore

Прогон `59e0014d2fdc` (VK WorkSpace + `task_desription.md`, `main` на `8f921e8`) упал
на стадии `plan` через 736 с:

```
InferenceError: DeckPlan: ответ не прошёл валидацию за 3 попыток
variant — String should match pattern '^[A-Z]$' [input_value='report']
```

Модель положила в `variant` назначение колоды из брифа. Грамматика llama.cpp `pattern`
не компилирует, поэтому он из схемы вырезается (#50), и значение прошло до Pydantic.
Все три попытки починки ушли на поле, которое планировщик **всё равно перезаписывает**
в `_ground` — вариант известен пайплайну до вызова модели.

То же у композитора: `slide_id`, `layout_id`, `variant`, `provenance` проставляет `_bind`,
а схема ответа их требовала. Тот же класс ошибки, что координаты в #65: схема просит
то, чего от модели не ждут.

## Propose

- `generate_model(..., overrides=...)`: поля, которые заполняет код, подставляются
  **до** валидации.
- `response_omit` (механизм из #65):
  - `deck_planner`: `variant, seed, language, narrative_check` — схема ответа теперь
    `deck_id` и `slides`;
  - `slide_composer`: плюс `slide_id, layout_id, variant, provenance` — схема ответа
    `blocks` и `speaker_note`.
- Планировщик и композитор передают `overrides` со значениями из пайплайна.

Короче схема — меньше токенов ответа и меньше мест, где модель может ошибиться.

## Verify

Три теста планировщика: чужой `variant` и нечисловой `seed` от модели не роняют план;
ответ без полей кода принимается; схема ответа — ровно `deck_id` и `slides`.
Полный набор: 1058 passed.
