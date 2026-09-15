# DeckForge — контекст проекта для OpenSpec

Сервис автоматической генерации презентаций в стиле произвольного шаблона.

## Как здесь работают

Спек-первым: сначала согласованная спецификация, потом код. Цикл:

```
/opsx:explore   обдумать задачу, посмотреть код, взвесить варианты (ничего не пишется)
/opsx:propose   создать openspec/changes/<id>/ с proposal.md, specs/, design.md, tasks.md
   ↓ человек ревьюит план
/opsx:apply     реализация по tasks.md
/opsx:verify    проверка против спецификации
/opsx:archive   change уезжает в archive/, specs/ обновляются
```

Правила работы — [AGENTS.md](../AGENTS.md). Границы слоёв и контракты —
[ARCHITECTURE.md](../ARCHITECTURE.md). Порядок работ — [IMPLEMENTATION.md](../IMPLEMENTATION.md).

## Инициализация

Требуется Node.js ≥ 20.19.0.

```bash
npm install -g @fission-ai/openspec@latest
openspec init
```

## Capabilities

Каждая — папка `openspec/specs/<capability>/spec.md`. Это же единица нарезки работ.

| Capability | Покрывает | Change |
|---|---|---|
| `template-parsing` | .pptx/.potx → TemplateManifest, кэш, версия парсера | (3) |
| `design-system-extraction` | тема, типошкала, сетка, декор | (4) |
| `layout-classification` | вид и вместимость макета без хардкода | (5) |
| `content-ingestion` | контент-пакет → ContentPackage, извлечение чисел | (7) |
| `deck-planning` | ContentPackage → DeckPlan, заголовки-выводы | (10) |
| `slide-composition` | DeckPlan + манифест → SlideIR | (11) |
| `layout-fitting` | text fitting, snapping, constraint-решатель | (12) |
| `native-visualization` | charts, tables, smartart, иконки | (14), (21) |
| `image-generation` | T2I ≤ 20B | (24) |
| `layout-variants` | три варианта вёрстки | (20) |
| `audit-deterministic` | геометрия, шаблон, плотность, целостность | (15) |
| `audit-semantic` | VLM-судья, 11 вопросов, фактчекинг | (18) |
| `audit-remediation` | авто-фиксы, HITL-выбор | (19) |
| `export-formats` | pptx / pdf / html | (16), (22) |
| `skill-registry` | версионирование промптов и скиллов | (9) — готово |
| `pipeline-orchestration` | LangGraph-граф, чекпойнты, бюджет времени | (17) |
| `service-api` | FastAPI, очередь, артефакты | (23) |
| `web-ui` | загрузка, превью, выбор фиксов, скачивание | (23) |
