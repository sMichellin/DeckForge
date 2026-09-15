# AGENTS.md — правила работы в этом репозитории

Правила одинаковы для AI-агента и для человека. Они существуют затем, чтобы решение
не оказалось заточенным под три знакомых шаблона: на защите шаблон будет незнакомый.

## Порядок

1. Прочитать [ARCHITECTURE.md](ARCHITECTURE.md) §1–§6 и [IMPLEMENTATION.md](IMPLEMENTATION.md).
2. Работать по циклу OpenSpec (`openspec/`): `explore → propose → apply → verify → archive`.
   **Код без принятого change-предложения не пишется.**
3. Один change = одна capability = одна ветка = один PR. Кросс-слойные правки разбивать.
4. Спорный момент — не «чинить на ходу», а создать предложение с обоснованием
   и обновить ARCHITECTURE.md в том же change.

## Нерушимое

| # | Правило | Чем проверяется |
|---|---|---|
| 1 | Слой не импортирует слой выше себя; `domain` не знает про I/O | `tests/unit/test_architecture_boundaries.py` |
| 2 | Никаких констант конкретных шаблонов: ни RGB, ни имён гарнитур, ни EMU, ни имён макетов | `scripts/lint_no_template_constants.py` |
| 3 | Промпты — только в `prompts/`, загрузка только через `deckforge.registry` | тест `test_prompts_are_not_hardcoded_in_src` |
| 4 | LLM не пишет .pptx и не пишет код вёрстки — только валидируемый `SlideIR` | ADR-001 |
| 5 | Цвет в IR — имя из темы, не `#RRGGBB` | схема `ColorRef` + `test_rgb_literal_is_not_a_valid_color_ref` |
| 6 | Кегль — только из `manifest.typography_scale` | `domain.rules.next_size_down` |
| 7 | Каждая новая проверка аудита — с тестом на нарушителе **и** на норме | ревью + `test_declared_checks_are_implemented` |
| 8 | Новая зависимость — через `poetry add`, с обоснованием в change | ревью |
| 9 | Локально ничего не устанавливается: всё через `podman` и `make` | — |
| 10 | Любая правка парсера или композитора проверяется на **холодном** шаблоне | `tests/e2e/test_cold_template.py` |

## Что значит «не зашито под шаблон»

Плохо:

```python
if layout.name == "Заголовок и содержимое":     # имя макета конкретного шаблона
    title_size = Pt(40)                          # кегль из головы
    accent = RGBColor(0xE4, 0x00, 0x2B)          # фирменный цвет одной компании
```

Хорошо:

```python
layout = manifest.layouts_of_kind(LayoutKind.BULLETS)[0]   # тип, а не имя
title_size = manifest.typography(TextRole.TITLE).size_pt   # шкала шаблона
accent = ColorRef.ACCENT1                                   # ссылка на тему
```

Разница простая: система должна знать **способ получить ответ** для любого шаблона,
а не сам ответ для одного.

## Команды

```bash
make image      # собрать образ
make test       # тесты
make lint       # ruff
make typecheck  # mypy
make gates      # гейты C1/C2 и C6
make schemas    # перегенерировать JSON-схемы после правки доменных моделей
```

После изменения любой модели в `src/deckforge/domain/` обязательно `make schemas`:
`schemas/*.schema.json` — golden-файлы контракта, и их расхождение с моделями валит тесты.

## Контекст-гигиена

Перед реализацией (`/opsx:apply`) чистить контекст: история обсуждений в реализацию не тащится.
