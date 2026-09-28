# Прогоны фикстурами

Снимки готовых прогонов: план, IR колоды, контент, манифест шаблона, дизайн-система
и `run.json`. По ним потоки плана Б меряют правку **без модели и без стенда**
(change `the-deck-is-audited-offline`, эпик #242).

| Каталог | Шаблон | Прогон | Коммит |
|---|---|---|---|
| `2026-09-28/workspace` | VK WorkSpace | `c511fe7fa6e3` | `19e3b7e` |
| `2026-09-28/vk-tech` | VK Tech | `7c44e7475db4` | `19e3b7e` |
| `2026-09-28/education` | VK Education | `3a93c140202f` | `19e3b7e` |

Путь сборки — `legacy`, вариант A, seed 1341. База «до» плана Б по этим колодам —
`openspec/changes/the-deck-is-measured-by-plan-b/proposal.md`.

## Как пользоваться

```python
from deckforge.pipeline.replay import from_fixture, reaudit

run = from_fixture(Path("tests/fixtures/runs/2026-09-28/vk-tech"))
run.plan, run.deck, run.content, run.manifest, run.design_system, run.report
```

```bash
deckforge audit tests/fixtures/runs/2026-09-28/vk-tech -o audit.json   # переаудит
python scripts/plan_b_metrics.py tests/fixtures/runs/2026-09-28/*/     # мерило плана Б
```

Паспорт примеров в фикстуру не входит — его код меняется, и сохранённый паспорт устарел
бы. Считайте его по снимку: `with_passports(run.design_system, run.manifest, fonts)`.

## Чего в фикстурах нет

* **Файлов `.pptx`** — ни колоды (9–18 МБ), ни шаблона (13–24 МБ). Шаблоны заказчика
  в репозиторий не кладутся. Проверки, которым нужен файл колоды, переаудит называет
  в `skipped_checks`. Где взять файлы:
  * на стенде — `~/e2e-work/artifacts/runs/<прогон>/in/template.pptx` и `out/deck.pptx`;
  * у тимлида — `../data/Датасет/` рядом с репозиторием.
* **Превью слайдов.** Проверки по картинкам (`design.*`) переаудит пропускает.

## Как перевыгрузить

```bash
python scripts/export_run_fixture.py <каталог прогона стенда> --out tests/fixtures/runs/<дата>/<имя>
```

Выгрузка детерминирована: одинаковый прогон даёт одинаковые байты.
