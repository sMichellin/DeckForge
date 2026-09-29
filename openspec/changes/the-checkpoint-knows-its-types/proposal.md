# the-checkpoint-knows-its-types

План Б, тимлид. Capability `pipeline-orchestration`. Файл — `pipeline/run.py`.

## Explore

LangGraph (1.2, `langgraph-checkpoint` 3.x) восстанавливает из чекпойнта только типы из явного
списка (`allowed_msgpack_modules`). Наших типов в списке не было: каждое чтение снимка прогона
(`pipeline/replay.py`, `deckforge audit`, `scripts/export_run_fixture.py`) печатало по
предупреждению на тип — «Deserializing unregistered type … will be blocked in a future version».

Замер: чтение IR одной колоды штатным сериализатором — 6 предупреждений; в строгом режиме
(`LANGGRAPH_STRICT_MSGPACK=true`) колода возвращается **`dict`, а не `DeckIR`**. С очередным
обновлением LangGraph строгий режим станет обычным, и снимки 28.09 и 29.09, на которых стоит
всё мерило плана Б, перестанут читаться моделями.

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
