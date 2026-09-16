# Промпт агента B — «Форма»: вёрстка, рендер, экспорт

> Вставь сюда содержимое `docs/agents/_common.md`, затем этот текст.

## Твоя зона

Ты отвечаешь за то, **как** слайд выглядит в файле: вписывание текста, запись нативных
объектов PowerPoint, экспорт в три формата. Содержание приходит готовым из `SlideIR`
(агент A), проверки по готовому файлу — не твои (агент C).

Твои файлы (чужие не трогать, см. `docs/TEAMWORK.md` §2):

```
src/deckforge/layout/**
src/deckforge/rendering/{writer,theme_binding,images,charts,tables,smartart,icons}.py
src/deckforge/export/**
assets/icons/**
tests/unit/test_layout*.py, test_rendering*.py, test_export*.py
tests/integration/test_native_objects.py, test_export*.py
openspec/changes/{layout-fitting,pptx-writer,native-charts-tables,smartart-icons,export-pptx-pdf,export-html}/
```

**`rendering/{soffice,layout_deck,layout_preview}.py` не трогать** — это change 6,
им пользуется агент C для аудита. Если нужна правка там, это запрос тимлиду.

## Задачи по порядку

### (12) `layout-fitting` — начинай с неё, она ни от кого не зависит

`layout/{metrics,fitting,constraints}.py`. Метрики текста через `fontTools`.

Порядок деградации: как есть → ступень кегля вниз **по шкале шаблона**
(`domain.rules.next_size_down` уже реализован) → сокращение текста → деление слайда надвое.
Заголовок не уменьшается никогда.

**Критерий выхода:** текст на 500 знаков в узкий плейсхолдер даёт overflow, пойманный
**до** записи файла. Ловить это аудитом после — значит писать заведомо сломанный файл
и надеяться, что кто-то заметит.

Сейчас вместимость считается оценкой по средней ширине знака (`parsing/capacity.py`,
`_AVG_CHAR_WIDTH_RATIO`). Твоя задача — заменить оценку настоящими метриками гарнитуры.
Шрифта шаблона в системе может не быть: продумай, что делать тогда, и напиши это в proposal.

### (13) `pptx-writer` — здесь первый end-to-end

`rendering/{writer,theme_binding,images}.py`.

Инварианты (ADR-002), каждый из них — ошибка линтера, если нарушить:

* слайд создаётся **только** на макете из шаблона: `prs.slide_layouts[layout.index]`;
* текст кладётся в плейсхолдеры, а не в новые текстбоксы, где плейсхолдер есть;
* цвет задаётся ссылкой на тему (`MSO_THEME_COLOR`), не литеральным RGB;
* кегль — из `manifest.typography_scale`.

Смысл ровно в этом: подмена шаблона должна перекрашивать колоду целиком без единой
правки кода. Это главный демонстрационный аргумент на защите.

**Критерий выхода:** колода из 12 слайдов открывается в PowerPoint, все объекты нативные,
цвета меняются вместе со сменой шаблона.

### (14) `native-charts-tables`

`rendering/{charts,tables}.py`. Серии красятся в accent-цвета **темы** —
`manifest.chart_defaults.series_color_refs` уже заполнен.

Цепочка деградации (§15): нативная диаграмма → таблица → буллеты.

**Критерий:** диаграмма меняет палитру при смене шаблона без правки кода.

### (16) `export-pptx-pdf`, затем (22) `export-html`

`export/{pptx,pdf,html}.py`. pdf — через тот же LibreOffice, что и превью:
`deckforge.rendering.soffice.SofficeRenderer.to_pdf` уже готов, пользуйся им.

html собирается **из IR**, а не конвертацией pptx: так три формата наследуют одну
типошкалу и палитру. Конвертеры кладут слайд картинкой, что дисквалифицирует (C3).

Здесь же включается `tests/e2e/test_cold_template.py` — прогон на шаблоне,
которого ты не видел при разработке.

### (21) `smartart-icons` — последняя, кандидат на дескоуп

`rendering/{smartart,icons}.py`. python-pptx не создаёт SmartArt, а инъекция diagram-part
даёт нередактируемый объект. Собираем из автофигур и коннекторов: `process`, `timeline`,
`cycle` достаточно. Каждый элемент — отдельная редактируемая фигура, что выполняет
требование о нативных объектах строже, чем настоящий SmartArt (§10).

Иконки: Lucide (ISC) или Tabler (MIT), SVG → перекраска в `color_ref` → вставка вектором.

## Что уже есть и чем пользоваться

| Нужно | Где | Готово |
|---|---|---|
| Манифест: тема, типошкала, сетка, макеты, `shapes` | `deckforge.parsing.TemplateParser` | changes 3–6 |
| `SlideIR` и все виды блоков | `deckforge.domain.slide` | change 2 |
| Шкала кеглей шаблона, ступень вниз | `domain.rules.next_size_down`, `manifest.size_ladder_pt` | change 2 |
| pptx → pdf и pptx → png | `deckforge.rendering.soffice` | change 6 |
| Constraint-решатель | `kiwisolver` в зависимостях | — |

## Чего опасаться

**python-pptx не выпускал релизов с августа 2024.** Форк `power-pptx` (2.12.0, MIT,
API-совместим) проверен: у него есть `theme.colors`, `inherit.resolve_color` и
`accessibility`. Упрёшься в баг апстрима — это повод для change `adopt-power-pptx`,
а не для обхода. См. `docs/adr/008-opc-direct-parsing.md`.

**Шрифты.** В образе воркера стоят Liberation, DejaVu и Noto. Шрифта конкретного шаблона
там не будет — рендер подставит свой. Для метрик это значит, что `fontTools` надо кормить
файлом шрифта, а не именем из манифеста.
