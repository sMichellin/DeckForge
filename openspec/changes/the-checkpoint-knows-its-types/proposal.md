# the-checkpoint-knows-its-types

План Б, тимлид. Capability `pipeline-orchestration`. Файл — `pipeline/run.py`.

## Explore

LangGraph (1.2, `langgraph-checkpoint` 3.x) восстанавливает из чекпойнта только типы из явного
списка (`allowed_msgpack_modules`). Наших типов в списке не было: каждое чтение снимка прогона
(`pipeline/replay.py`, `deckforge audit`, `scripts/export_run_fixture.py`) печатало по
предупреждению на тип — «Deserializing unregistered type … will be blocked in a future version».

Замер:
* чтение трёх настоящих чекпойнтов стенда plan-b (`from_checkpoint`, прогоны 29.09) —
  **28 предупреждений**; IR одной колоды через штатный сериализатор напрямую — 6;
* строгий режим (`LANGGRAPH_STRICT_MSGPACK=true`): сериализатор напрямую отдаёт колоду
  **`dict`, а не `DeckIR`**. `from_checkpoint` в строгом режиме пока читает модели — состояние
  графа приводится к схеме `DeckState` при `aget_state`, — так что поломки сегодня нет;
  есть шум в каждом отчёте и зависимость от того, что LangGraph и дальше будет приводить
  состояние, а не отдавать сырое.

## Propose

* `checkpoint_types()` — модели (`BaseModel`) и перечисления (`Enum`) из модулей, чьи типы лежат
  в состоянии графа: весь пакет `deckforge.domain`, `designsystem.models`, `composition.assign`.
  Список собирается обходом модулей, а не перечнем имён: новая модель домена попадает сама.
* `checkpoint_serde()` — `JsonPlusSerializer(allowed_msgpack_modules=checkpoint_types())`.
* `open_checkpointer` ставит его и памяти, и sqlite (у `from_conn_string` параметра нет —
  подмена на готовом сохранителе до первого чтения; `aiosqlite` напрямую не импортируется,
  новой зависимости нет).

## Verify

`tests/unit/test_the_checkpoint_knows_its_types.py`:

* список покрывает домен, дизайн-систему и назначения (норма); каждая модель `domain.content`
  в нём без регистрации (норма);
* строгий режим в отдельном процессе: IR колоды, манифест и назначения 29.09 возвращаются
  моделями (нарушитель без правки — штатный сериализатор отдаёт `dict`);
* чтение через `open_checkpointer` не предупреждает ни об одном типе (нарушитель без правки —
  6 предупреждений на колоду).

Стенд plan-b, три чекпойнта 29.09 через `from_checkpoint`: предупреждений 28 → **0**; в строгом
режиме колода, манифест и дизайн-система — модели.
