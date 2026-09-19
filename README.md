# DeckForge

Сервис автоматической генерации презентаций в стиле **произвольного** шаблона.
Кейс «Цифровой дизайнер презентаций», ЛЦТ 2026.

На вход — незнакомый `.pptx`/`.potx` и контент-пакет. На выходе — колода из 10–15 слайдов
нативными объектами PowerPoint, в трёх вариантах вёрстки, с отчётом аудита, за ≤ 5 минут.

---

## Как это устроено в двух абзацах

Шаблон читается как **набор правил**, а не как картинка: палитра, типографическая шкала,
сетка, макеты и их вместимость извлекаются в самодостаточный артефакт `TemplateManifest`.
Дальше генерация не имеет доступа к исходному файлу — только к манифесту.

Языковая модель **никогда не пишет .pptx и не пишет код вёрстки**. Она заполняет строгий
JSON (`SlideIR`), который валидируется до создания файла. Сборку делает детерминированный
рендерер на python-pptx: слайд создаётся на макете из шаблона, текст кладётся в плейсхолдеры,
цвет задаётся ссылкой на тему. Поэтому соответствие фирменному стилю — следствие архитектуры,
а не результат удачного промпта. Подробности и альтернативы — в [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Запуск

Требуется только **podman** (или docker). Локально ничего устанавливать не нужно:
Python, Poetry, LibreOffice и шрифты живут в образах.

```bash
cp .env.example .env          # укажите эндпоинт инференса
make image                    # собрать образ приложения
make up                       # поднять сервисы: API, воркер, UI, LibreOffice, Redis, LanguageTool
```

UI — <http://localhost:8501>, API — <http://localhost:8080/docs>.

### Воспроизводимый прогон конфиг-файлом

```bash
podman run --rm -v $PWD:/app:z -w /app localhost/deckforge:dev \
  deckforge generate templates/unknown.pptx content/ \
  --brief content/brief.yaml \
  --config configs/profiles/final.yaml \
  --variant all
```

Seed фиксирован в конфиге, поэтому повторный запуск даёт тот же результат.
Профили: `configs/profiles/{dev,demo,final}.yaml`.

### Рабочие команды

```bash
make test        # тесты
make lint        # ruff
make typecheck   # mypy
make gates       # гейты ТЗ: лицензии моделей (C1/C2) и отсутствие констант шаблона (C6)
make schemas     # перегенерировать JSON-схемы из доменных моделей
make checks      # показать реестр проверок аудита
```

---

## Переменные окружения

Полный список — в [.env.example](.env.example). Секретов в репозитории нет.

| Переменная | Назначение |
|---|---|
| `DECKFORGE_MODELS_CONFIG` | какой реестр моделей брать: `models.yaml` (HuggingFace), `models.openrouter.yaml`, `models.ollama.yaml` |
| `DECKFORGE_LLM_BASE_URL`, `DECKFORGE_LLM_API_KEY` | OpenAI-совместимый эндпоинт LLM (vLLM, роутер HF, OpenRouter, Ollama, VK Inference) |
| `DECKFORGE_VLM_BASE_URL`, `DECKFORGE_VLM_API_KEY` | VLM: классификация макетов и аудит-судья |
| `DECKFORGE_T2I_BASE_URL`, `DECKFORGE_T2I_API_KEY` | text-to-image (задача «со звёздочкой») |
| `DECKFORGE_REDIS_URL` | очередь arq |
| `DECKFORGE_LANGUAGETOOL_URL` | сервер проверки орфографии |
| `DECKFORGE_SOFFICE_BIN` | LibreOffice headless для pptx → png/pdf |

---

## Структура репозитория

```
configs/     конфиги запуска, реестр моделей, оси вариантов, реестр проверок
prompts/     промпты по версиям (C9): system.j2, user.j2, schema.json, meta.yaml
skills/      конфиги шагов воркфлоу по версиям
src/deckforge/
  domain/      Pydantic-контракты между слоями — единственный способ передачи данных
  parsing/     .pptx → TemplateManifest, контент → ContentPackage
  planning/    → DeckPlan (состав и порядок слайдов)
  composition/ → SlideIR (наполнение конкретного макета)
  layout/      вписывание текста, авто-кегль, детект переполнения до записи файла
  rendering/   SlideIR → нативные объекты python-pptx
  audit/       реестр проверок, VLM-судья, авто-фиксы
  export/      pptx / pdf / html из одного источника
  inference/   клиент LLM/VLM/T2I, guided decoding, кэш
  pipeline/    LangGraph-граф, HITL, чекпойнты
schemas/     JSON-схемы контрактов (golden-файлы)
scripts/     CI-гейты и сборка пакета сдачи
docker/      образы приложения и LibreOffice
```

---

## Документация

| Документ | О чём |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | пайплайн, границы слоёв, контракты, ADR |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | порядок реализации: что сделано, что дальше, чем закрывается |
| [MODELS.md](MODELS.md) | модели, лицензии, размеры, системные требования |
| [AUDIT.md](AUDIT.md) | все проверки и область покрытия |
| [PLAN.md](PLAN.md) | календарный план и чек-лист сдачи |
| [docs/inference-providers.md](docs/inference-providers.md) | где брать инференс: что проверено и что дисквалифицирует |
| [AGENTS.md](AGENTS.md) | правила работы для AI-агента и для человека |
| [docs/adr/](docs/adr/) | архитектурные решения с обоснованием |

---

## Где брать инференс

Все провайдеры говорят по протоколу OpenAI, поэтому переключение — это две переменные
окружения и выбор реестра моделей. Код модель по имени нигде не называет.

| Путь | Чем платим | Пригодные по ТЗ модели |
|---|---|---|
| **OVHcloud AI Endpoints** | Qwen3.8-27B бесплатно | 7 пригодных моделей, включая открытую Mistral Small 3.2 24B |
| **Groq** | бесплатно, 8000 токенов/мин | Qwen3.8-27B — 0.3 с на вызов |
| **Локальный Ollama** | ничем | `qwen3:8b`, `qwen3-vl:8b`, без лимитов |
| Роутер HuggingFace | месячный лимит кредитов аккаунта | Qwen3.8-27B, Qwen3-VL-30B-A3B |
| OpenRouter | по токенам, от $0.10 за 1M | Qwen3-VL-8B (та самая из §9.2), Qwen3.8-27B |
| vLLM на своей GPU | железом | любые |

**Бесплатного облачного инференса с пригодными моделями не существует.** На роутере
HuggingFace бесплатных провайдеров 0 из 332 пар модель×провайдер; у OpenRouter
23 бесплатные позиции из 446 — и все это Claude, GPT, Gemini, Grok и GLM: закрытые
веса либо больше 35B, то есть прямая дисквалификация по ТЗ. «Бесплатность» HF — это
месячный лимит кредитов на аккаунт, и он кончается за пару сотен вызовов.

```bash
# локально и бесплатно
ollama pull qwen3:8b && ollama pull qwen3-vl:8b
export DECKFORGE_MODELS_CONFIG=models.ollama.yaml
export DECKFORGE_LLM_BASE_URL=http://localhost:11434/v1 DECKFORGE_LLM_API_KEY=ollama
export DECKFORGE_VLM_BASE_URL=http://localhost:11434/v1 DECKFORGE_VLM_API_KEY=ollama
```

## Ограничения

Раздел заполняется честно и по мере работы — заявленная граница ценится выше незаметно
отсутствующей функции (PLAN.md §2).

**Известно на 15.09:**

- Проект на этапе каркаса: домен, контракты, реестры и гейты готовы; слои парсинга,
  композиции, вёрстки и аудита — в работе по порядку из [IMPLEMENTATION.md](IMPLEMENTATION.md).
- `SmartArt` реализуется составными компонентами из автофигур, а не OOXML-объектом
  `diagram`: python-pptx его не создаёт, а инъекция готового XML даёт нередактируемый
  объект, что нарушило бы требование о нативных объектах. Обоснование — ARCHITECTURE.md §10.
- Генерация изображений (text-to-image) — задача «со звёздочкой», плановый кандидат
  на дескоуп при нехватке времени.
- Интерфейс на Streamlit, не Next.js: сознательный выбор в пользу устойчивости демо.

## Лицензия

MIT. Все используемые модели — с открытыми весами под Apache-2.0 / MIT, см. [MODELS.md](MODELS.md).
