"""Авто-кегль и стратегия вписывания. Changes (12) `layout-fitting`, (14) таблицы и KPI,
(21) составные компоненты.

Порядок деградации (из METHOD прежнего проекта, переписано без брендовых констант):
1. как есть → 2. ступень кегля вниз по шкале шаблона → 3. сокращение текста LLM →
4. деление слайда надвое. Заголовок не уменьшается никогда.

Слой `layout` LLM не вызывает (ARCHITECTURE.md §3): шаги 3 и 4 он **назначает** в
`FitResult.strategy`, а выполняют их композиция и граф. Главное — переполнение видно
в `SlideIR.fit_report` до того, как рендерер создаст файл.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from deckforge.designsystem.models import Zone
from deckforge.domain.base import BBox
from deckforge.domain.content import ContentPackage, Dataset
from deckforge.domain.enums import SmartArtPattern, TextRole
from deckforge.domain.rules import next_size_down, next_size_up
from deckforge.domain.slide import (
    BulletsBlock,
    CalloutBlock,
    FitResult,
    KpiBlock,
    QuoteBlock,
    SlideIR,
    SmartArtBlock,
    TableBlock,
    TextBlock,
)
from deckforge.domain.template import (
    ComponentKind,
    LayoutSpec,
    TemplateManifest,
    TypographyStep,
)
from deckforge.domain.units import EMU_PER_PT, TEXT_FRAME_INSET_Y_EMU
from deckforge.layout.boxed import BoxedBlock, paragraphs, style_of, text_frame
from deckforge.layout.by_design import READING_FLOOR_PT, DesignRules, KpiSizes
from deckforge.layout.diagram import (
    Component,
    buildable_patterns,
    diagram_geometry,
    goes_by_design,
)
from deckforge.layout.errors import LayoutFitError
from deckforge.layout.fonts import FontLibrary
from deckforge.layout.lists import draws_icons, icon_column, icon_text_frame
from deckforge.layout.metrics import (
    line_height_emu,
    longest_word_em,
    measure_text,
    split_paragraphs,
    usable_height_emu,
    usable_width_emu,
)
from deckforge.layout.tabular import table_cells, table_has_header

__all__ = [
    "LayoutFitError",
    "fit_block",
    "fit_boxed",
    "fit_icon_list",
    "fit_kpi",
    "fit_slide",
    "fit_smartart",
    "fit_table",
    "fit_text",
    "table_row_heights",
]

#: Во сколько раз текст может не влезать, чтобы его ещё имело смысл сокращать, а не делить
#: слайд. 1,5 — срезать до трети: больше LLM теряет смысл, а не воду. Это политика
#: вёрстки, а не свойство шаблона.
SHORTEN_MAX_OVERFLOW = 1.5

AS_IS = "as_is"
SHRINK = "shrink"
SHORTEN = "shorten"
SPLIT = "split"
GROW = "grow"
#: Кегль ниже порога читаемости по правилу D06: на ступенях не ниже порога не встаёт даже
#: первое слово, сокращение свело бы блок к нулю — блок остаётся на ступени под порогом,
#: на которой встаёт. Узел `fit` назовёт это в заметке после запроса 0 тимлиду (proposal
#: `a-size-below-reading-is-not-a-fit`); до того пометка видна только в `fit_report`.
BELOW_READING = "below_reading"

#: Ниже этой доли своей рамки свободный блок теряется в пустоте: текст жмётся к верхнему
#: краю, а остальное поле остаётся белым. Прогон 693d464d54fb: четыре строки в рамке
#: высотой двенадцать сантиметров — слайд выглядит пустым, хотя переполнения нет.
FREE_BLOCK_FILL_SHARE = 0.5

#: На сколько ступеней шкалы кегль блока в зоне рецепта уходит от стартового, прежде чем
#: текст сокращается (D02, §11). Приёмка RG29: тело спускалось 16 → 7,8 pt — текст цел,
#: но читать его уже нельзя, и это хуже сокращения. Число — как у уступки заголовка
#: (`_TITLE_STEPS_DOWN` узла `fit`): одно правило «сколько кегля отдаём ради текста».
#: Политика вёрстки, а не свойство шаблона.
_ZONE_STEPS_DOWN = 2

#: Какую долю ширины меньшей из двух зон должна перекрывать зона под ней, чтобы считаться
#: соседом снизу (RG39) — D07, RG46. Меньшее перекрытие — волосок раскладки автора, а не
#: соседство: у VK Tech подпись «Вставить фото» задета соседом на 2,3 % ширины, высота
#: урезалась ниже строки её кегля, рамка становилась якорем (D02), и две строки 10 pt
#: ложились поверх соседей. Политика вёрстки, а не свойство шаблона; порог лежит
#: в разрыве 2,3 %…20 % замера трёх шаблонов кейса.
_NEIGHBOUR_OVERLAP_SHARE = 0.1


def _sizes(
    manifest: TemplateManifest,
    start_pt: float,
    allow_shrink: bool,
    min_pt: float | None = None,
    *,
    keep_start: bool = False,
    max_steps: int | None = None,
) -> Iterator[float]:
    """Кегли для перебора: старт, привязанный к шкале шаблона, и ступени вниз.

    `min_pt` — предел, ниже которого спуск не идёт. Стартовый кегль он не поднимает:
    кто задал блоку кегль явно, тот уже принял решение (см. `_titles_yield_size`). Но старт
    не ниже предела, привязанный к шкале ступенью ниже него, — уже спуск, и он проходит ту же
    проверку (RG35): вместо ступени под пределом берётся наименьшая ступень не ниже него —
    пол. Перебор никогда не пуст: исход любого пути — ступень шкалы с посчитанной высотой.

    `keep_start` — старт не привязывается к шкале: это кегль автора шаблона из его же
    фигуры (зона рецепта, RG29), как кегль плейсхолдера. Привяжи его — и текст, который
    на своём кегле помещается, всё равно менял бы кегль на каждой зоне с кеглем не из
    шкалы. Ступени вниз — по-прежнему только по шкале (правило 6).

    `max_steps` — сколько ступеней вниз от старта допустимо (`_ZONE_STEPS_DOWN`). Старт вне
    шкалы, приведённый к ней, — уже ступень: кегль от этого меньше, чем назначил автор.
    """
    ladder = manifest.size_ladder_pt
    size: float | None = start_pt
    steps = 0
    if ladder and start_pt not in ladder and not keep_start:
        # Кегль вне шкалы шаблона не используется даже как стартовый (ADR-002).
        size = next_size_down(manifest, start_pt) or min(ladder)
        steps = 1
        if min_pt is not None and size < min_pt <= start_pt:
            size = min((s for s in ladder if s >= min_pt), default=size)
    while size is not None:
        yield size
        if not allow_shrink or (max_steps is not None and steps >= max_steps):
            return
        steps += 1
        size = next_size_down(manifest, size)
        if size is not None and min_pt is not None and size < min_pt:
            return


def _fits(size: float, start_pt: float, lines: int, required: int) -> FitResult:
    return FitResult(
        final_size_pt=size,
        overflow=False,
        lines=lines,
        required_cy_emu=required,
        strategy=AS_IS if size == start_pt else SHRINK,
    )


def _overflow(
    size: float, lines: int, required: int, available: int, splittable: bool
) -> FitResult:
    ratio = required / available if available else float("inf")
    return FitResult(
        final_size_pt=size,
        overflow=True,
        lines=lines,
        required_cy_emu=required,
        strategy=SPLIT if splittable and ratio > SHORTEN_MAX_OVERFLOW else SHORTEN,
    )


def fit_text(
    text: str,
    *,
    box: BBox,
    manifest: TemplateManifest,
    start_size_pt: float,
    font_family: str,
    allow_shrink: bool = True,
    min_size_pt: float | None = None,
    bold: bool = False,
    italic: bool = False,
    line_spacing: float = 1.0,
    fonts: FontLibrary | None = None,
    author_start: bool = False,
    words_bold: bool = False,
    anchor: bool = False,
    max_steps: int | None = None,
    reading_floor_pt: float | None = None,
) -> FitResult:
    """Подбирает кегль по шкале шаблона; не влезло на нижней ступени — назначает стратегию.

    Кегль вмещается, когда хватает высоты **и** самое длинное слово уже строки рамки.
    Второе — отдельное условие, не следствие площади (RG29): слово шире строки PowerPoint
    рвёт по знакам, строк от этого прибавляется, но на s05 VK WorkSpace место было —
    и на превью стояло «извлечен / ие» при 54 pt в рамке 3 879 511 EMU.

    `author_start` — старт есть кегль автора шаблона в его же рамке (зона рецепта): он
    не привязывается к шкале (D01, §10в).

    `words_bold` — ширина слов меряется полужирным: начертание рамки неизвестно, а обычное
    недооценивает ровно тот разрыв слова, ради которого условие заведено (§10б).

    `anchor` — рамка есть якорь текста, а не коробка: высота не ограничивает, кегль
    вмещается, как только самое длинное слово уже строки (D02, §11). Так у автора набраны
    карточки VK Tech: рамка ниже строки своего кегля, текст из неё растёт вниз. Это
    обобщает строку автора (§10в): полей и интервала фигуры мы не знаем, и модель строки
    «не вписала» бы текст примера в его собственную рамку — титул 144 pt, заголовки 36 pt
    в полосе 626 869 EMU. Рамка, которая строку своего кегля держит, меряется по высоте:
    одна строка в ней встаёт и так.

    `max_steps` — предел спуска по шкале от стартового кегля (см. `_sizes`); не влезло
    в пределе — стратегия сокращения, как на нижней ступени.

    `reading_floor_pt` — порог читаемости (RG35): пол спуска — наибольшее из него и
    `min_size_pt`. Не влезло на ступенях не ниже пола — сокращение. Исключение D06: когда
    на этих ступенях не встаёт даже первое слово (сокращение оставляет начало текста и свело
    бы блок к нулю), спуск идёт как без порога, и кегль под порогом помечается `BELOW_READING`.
    """
    floors = [f for f in (min_size_pt, reading_floor_pt) if f is not None]
    floor = max(floors) if floors else None
    descend = partial(
        _descend, box=box, manifest=manifest, start_size_pt=start_size_pt,
        font_family=font_family, allow_shrink=allow_shrink, bold=bold, italic=italic,
        line_spacing=line_spacing, fonts=fonts, author_start=author_start,
        words_bold=words_bold, anchor=anchor, max_steps=max_steps,
    )
    result = descend(text, min_size_pt=floor)
    words = text.split()
    if not result.overflow or floor == min_size_pt or not words:
        return result
    if not descend(words[0], min_size_pt=floor).overflow:
        return result
    below = descend(text, min_size_pt=min_size_pt)
    # Ступень под порогом — только та, на которой блок встаёт (D06); иначе исход на полу.
    return result if below.overflow else below.model_copy(update={"strategy": BELOW_READING})


def _descend(
    text: str,
    *,
    box: BBox,
    manifest: TemplateManifest,
    start_size_pt: float,
    font_family: str,
    allow_shrink: bool,
    min_size_pt: float | None,
    bold: bool,
    italic: bool,
    line_spacing: float,
    fonts: FontLibrary | None,
    author_start: bool,
    words_bold: bool,
    anchor: bool,
    max_steps: int | None,
) -> FitResult:
    """Спуск по ступеням `_sizes` до первой, на которой текст встаёт (см. `fit_text`)."""
    available = usable_height_emu(box)
    line = usable_width_emu(box)
    word_bold = words_bold and not bold
    # Слово шире от кегля линейно: полужирная ширина в em меряется один раз, без переноса.
    word_em = (
        longest_word_em(text, font_family=font_family, bold=True, italic=italic, fonts=fonts)
        if word_bold
        else None
    )

    size, lines, required = start_size_pt, 0, 0
    for size in _sizes(
        manifest, start_size_pt, allow_shrink, min_size_pt,
        keep_start=author_start, max_steps=max_steps,
    ):
        m = measure_text(
            text, font_family=font_family, size_pt=size, box=box,
            line_spacing=line_spacing, bold=bold, italic=italic, fonts=fonts,
        )
        lines, required = m.lines, m.height_emu
        word = m.longest_word_emu if word_em is None else round(word_em * size * EMU_PER_PT)
        if word > line:
            continue
        if required <= available or anchor:
            return _fits(size, start_size_pt, lines, required)
    splittable = allow_shrink and len(split_paragraphs(text)) > 1
    return _overflow(size, lines, required, available, splittable)


def _step_for(role: TextRole, manifest: TemplateManifest) -> TypographyStep:
    step = manifest.typography(role) or manifest.typography(TextRole.BODY)
    if step is None:
        raise LayoutFitError(f"в типошкале шаблона нет ни роли {role}, ни основного текста")
    return step


def _font_of(step: TypographyStep, manifest: TemplateManifest) -> str:
    return manifest.theme.fonts.get(step.font_ref) or manifest.theme.fonts.minor_latin


def _table_rows(
    block: TableBlock,
    box: BBox,
    manifest: TemplateManifest,
    size_pt: float,
    dataset: Dataset | None,
    fonts: FontLibrary | None,
) -> list[tuple[int, int]]:
    """(строк текста, высота в EMU) для каждой строки таблицы при данном кегле."""
    cells = table_cells(block, dataset)
    columns = max(len(row) for row in cells)
    step = _step_for(TextRole.BODY, manifest)
    font = _font_of(step, manifest)
    column = BBox(x=box.x, y=box.y, cx=max(1, box.cx // columns), cy=box.cy)
    header = block.first_row_header and table_has_header(block)
    out = []
    for index, row in enumerate(cells):
        bold = step.bold or (header and index == 0)
        lines = max(
            max(1, measure_text(cell, font_family=font, size_pt=size_pt, box=column,
                                bold=bold, fonts=fonts).lines)
            for cell in row
        )
        out.append((lines, round(lines * line_height_emu(size_pt)) + 2 * TEXT_FRAME_INSET_Y_EMU))
    return out


def table_row_heights(
    block: TableBlock,
    box: BBox,
    manifest: TemplateManifest,
    size_pt: float,
    *,
    dataset: Dataset | None = None,
    fonts: FontLibrary | None = None,
) -> list[int]:
    """Высоты строк, которые писатель обязан поставить таблице.

    Без них python-pptx делит рамку на строки поровну, и строка с переносами вылезает
    за рамку, хотя сумма высот в неё помещалась.
    """
    return [height for _, height in _table_rows(block, box, manifest, size_pt, dataset, fonts)]


def fit_table(
    block: TableBlock,
    box: BBox,
    manifest: TemplateManifest,
    *,
    dataset: Dataset | None = None,
    fonts: FontLibrary | None = None,
    reading_floor_pt: float = READING_FLOOR_PT,
) -> FitResult:
    """Таблица с колонками равной ширины: высота строки — самая высокая ячейка.

    Поля ячейки PowerPoint по умолчанию совпадают с полями текстовой рамки, поэтому ячейка
    меряется как рамка шириной в колонку. Кегль — от роли `body` вниз по шкале шаблона,
    но не ниже порога читаемости (RG35): не влезла — переполнение, и писатель пишет её
    буллетами, которые держат тот же порог.
    """
    step = _step_for(TextRole.BODY, manifest)
    rows_count = len(table_cells(block, dataset))
    size, lines, required = step.size_pt, 0, 0
    for size in _sizes(manifest, step.size_pt, allow_shrink=True, min_pt=reading_floor_pt):
        rows = _table_rows(block, box, manifest, size, dataset, fonts)
        lines = sum(n for n, _ in rows)
        required = sum(h for _, h in rows)
        if required <= box.cy:
            return _fits(size, step.size_pt, lines, required)
    return _overflow(size, lines, required, box.cy, splittable=rows_count > 2)


def fit_kpi(
    block: KpiBlock,
    box: BBox,
    manifest: TemplateManifest,
    *,
    fonts: FontLibrary | None = None,
    sizes: KpiSizes | None = None,
) -> FitResult:
    """Показатели колонками. `final_size_pt` — кегль значения.

    `sizes` — кегли по дизайн-системе (`DesignRules.kpi_sizes`): значение начинается
    с ступени, которой шаблон сам набрал своё число, подпись — мелкий кегль числа.
    Шаблон ответил — выше своего кегля значение не растёт: это его размер, а не наш.
    Нет ответа — прежнее правило: значение от кегля `subtitle` вниз по шкале и рост
    до кегля заголовка (#87), подпись — кеглем `caption`.

    Значение верстается как текст: перенос между словами допустим, разрыв слова
    и разрыв числа — нет (см. `_value_holds_together`, B13). Это общее для обоих путей:
    иначе фразовое значение снова посадило бы весь блок на мелкий кегль."""
    value_step = manifest.typography(TextRole.SUBTITLE) or _step_for(TextRole.BODY, manifest)
    label_step = manifest.typography(TextRole.CAPTION) or _step_for(TextRole.BODY, manifest)
    column = BBox(x=box.x, y=box.y, cx=max(1, box.cx // len(block.items)), cy=box.cy)
    available = usable_height_emu(box)
    value_font = _font_of(value_step, manifest)

    def label_pt(value_pt: float) -> float:
        return sizes.label_for(value_pt, manifest) if sizes is not None else label_step.size_pt

    def measured(size_pt: float) -> tuple[bool, int, int]:
        """(значение верстается без разрывов, строк всего, нужная высота) при этом кегле."""
        whole, lines, required = True, 0, 0
        for item in block.items:
            value = measure_text(item.value, font_family=value_font, size_pt=size_pt,
                                 box=column, bold=value_step.bold, fonts=fonts)
            label = measure_text(item.label, font_family=_font_of(label_step, manifest),
                                 size_pt=label_pt(size_pt), box=column, fonts=fonts)
            whole = whole and _value_holds_together(
                item.value, value.lines, font=value_font, size_pt=size_pt,
                column=column, bold=value_step.bold, fonts=fonts
            )
            lines = max(lines, value.lines + label.lines)
            required = max(required, value.height_emu + label.height_emu)
        return whole, lines, required

    start = sizes.value_pt if sizes is not None else value_step.size_pt
    size, lines, required = start, 0, 0
    for size in _sizes(manifest, start, allow_shrink=True):
        whole, lines, required = measured(size)
        if whole and required <= available:
            fitted = _fits(size, start, lines, required)
            if sizes is not None:
                return fitted
            return _grown_kpi(fitted, measured, manifest, available)
    return _overflow(size, lines, required, available, splittable=False)


def _value_holds_together(
    text: str,
    lines: int,
    *,
    font: str,
    size_pt: float,
    column: BBox,
    bold: bool,
    fonts: FontLibrary | None,
) -> bool:
    """Значение перенеслось без порчи.

    Одна строка — вопроса нет. Дальше два разных случая, которые прежде считались одним:

    * **Число** рвать нельзя: «1 200 ₽» в две строки читается как два числа — та же беда,
      что change `thousands-group-is-three-digits` лечил в парсере. Точку переноса
      измеритель не отдаёт, поэтому значение с цифрой требует одной строки целиком.
    * **Фраза** — обычный текст: «часы → минуты» переносится между словами, как подписи
      схемы в `fit_smartart`. Запрещён только разрыв по знакам внутри слова, поэтому
      каждое слово обязано встать в колонку целиком.

    Без этого разделения один фразовый показатель сажал весь блок на кегль, при котором
    фраза влезает в строку: VK WorkSpace s04 прогона 6c4277d898c3 — 14 pt при списке
    рядом в 23,4 pt.
    """
    if lines <= 1:
        return True
    if any(char.isdigit() for char in text):
        return False
    return all(
        measure_text(word, font_family=font, size_pt=size_pt, box=column,
                     bold=bold, fonts=fonts).lines <= 1
        for word in text.split()
    )


def _grown_kpi(
    result: FitResult,
    measured: Any,
    manifest: TemplateManifest,
    available: int,
) -> FitResult:
    """Поднимает кегль показателя, пока он занимает меньше половины отведённого.

    Рамку блоку считает решатель, и одна строка цифр в ней — это пустой слайд
    (прогон f0eb600a3ad7: ни одного слайда в норме плотности при показателях
    на восьми из девяти). Потолок — кегль заголовка шаблона: цифра вровень
    с заголовком нормальна, крупнее — уже кричит.
    """
    if not available or (result.required_cy_emu or 0) >= FREE_BLOCK_FILL_SHARE * available:
        return result

    cap = _step_for(TextRole.TITLE, manifest).size_pt
    best = result
    size = next_size_up(manifest, result.final_size_pt)
    while size is not None and size <= cap:
        whole, lines, required = measured(size)
        if not whole or required > available:
            break
        best = FitResult(
            final_size_pt=size, overflow=False, lines=lines,
            required_cy_emu=required, strategy=GROW,
        )
        if required >= FREE_BLOCK_FILL_SHARE * available:
            break
        size = next_size_up(manifest, size)
    return best


def process_columns(
    items: Sequence[str],
    box: BBox,
    manifest: TemplateManifest,
    *,
    tile: Component | None = None,
    fonts: FontLibrary | None = None,
) -> int:
    """Сколько шагов процесса ставить в ряд, чтобы слово не рвалось по слогам (К5, круг 2).

    Самое большое число, при котором **самое длинное слово** каждой подписи встаёт в узел
    кеглем тела: строка шаблона в один ряд бывает такой узкой, что слово не влезает и на
    пороге читаемости. Education s07, прогон 29.09 — четыре шага в колонке 13 см: узлы по
    2,8 см, и «документов» рвётся на «докум ентов». Два ряда дают 5,8 см, один столбец —
    13 см, и слово встаёт целиком.

    Кегль тела, а не порог: лестница шаблона бывает короткой (у Education она кончается
    на 18 pt), и спускаться вписыванию некуда. Ни одно число не подошло — берётся один
    столбец: шире узла не бывает.
    """
    step = _step_for(TextRole.BODY, manifest)
    font = _font_of(step, manifest)
    count = len(items)
    for columns in range(count, 0, -1):
        labels = diagram_geometry(
            SmartArtPattern.PROCESS, count, box, tile, columns=columns
        ).labels
        if all(
            measure_text(word, font_family=font, size_pt=step.size_pt, box=label,
                         bold=step.bold, fonts=fonts).lines <= 1
            for text, label in zip(items, labels, strict=True)
            for word in text.split()
        ):
            return columns
    return 1


def fit_smartart(
    block: SmartArtBlock,
    box: BBox,
    manifest: TemplateManifest,
    *,
    fonts: FontLibrary | None = None,
    design: DesignRules | None = None,
    by_example: bool = False,
) -> FitResult:
    """Все подписи компонента одним кеглем: от `body` вниз по шкале, пока каждая не влезет
    в свою рамку из `diagram_geometry`. Разный кегль у соседних шагов выглядит ошибкой.

    Рамки узлов узкие, и слово в них рвётся по знакам: высота при этом влезает, но «Прове/рка»
    в узле — брак вёрстки. Поэтому подпись влезла, только если и каждое её слово встало
    в строку целиком.

    Плитка — из каталога дизайн-системы (`design.tile()`), без неё — из манифеста, как
    было: запись pptx и html берут её из того же места, иначе рамки подписей разошлись бы.

    Ниже порога читаемости (RG35) подписи не спускаются: не влезли — переполнение, и узел
    `fit` пишет схему списком тех же пунктов.

    `by_example` — путь сборки по примерам: на нём шаги процесса переносятся в несколько
    рядов, если рамка узкая (`diagram.process_columns`). Мерится та же геометрия, которую
    потом нарисует писатель: оба зовут `diagram_geometry` с одним и тем же путём."""
    step = _step_for(TextRole.BODY, manifest)
    font = _font_of(step, manifest)
    tile = design.tile() if design is not None else manifest.component(ComponentKind.TILE)
    columns = (
        process_columns(block.items, box, manifest, tile=tile, fonts=fonts)
        if by_example and block.pattern is SmartArtPattern.PROCESS
        else None
    )
    labels = diagram_geometry(
        block.pattern, len(block.items), box, tile, columns=columns
    ).labels
    available = min(usable_height_emu(label) for label in labels)

    def measured(size_pt: float) -> tuple[bool, int, int]:
        """(влезли ли все подписи целыми словами, строк, нужная высота) при кегле."""
        runs = [
            measure_text(text, font_family=font, size_pt=size_pt, box=label, bold=step.bold,
                         fonts=fonts)
            for text, label in zip(block.items, labels, strict=True)
        ]
        lines = max(m.lines for m in runs)
        required = max(m.height_emu for m in runs)
        whole_words = all(
            measure_text(word, font_family=font, size_pt=size_pt, box=label, bold=step.bold,
                         fonts=fonts).lines <= 1
            for text, label in zip(block.items, labels, strict=True)
            for word in text.split()
        )
        return required <= available and whole_words, lines, required

    floor = design.reading_floor_pt if design is not None else READING_FLOOR_PT
    size, lines, required = step.size_pt, 0, 0
    for size in _sizes(manifest, step.size_pt, allow_shrink=True, min_pt=floor):
        fits, lines, required = measured(size)
        if fits:
            return _grown_labels(
                _fits(size, step.size_pt, lines, required), measured, manifest, available
            )
    return _overflow(size, lines, required, available, splittable=False)


def _grown_labels(
    result: FitResult,
    measured: Any,
    manifest: TemplateManifest,
    available: int,
) -> FitResult:
    """Поднимает кегль подписей схемы, пока в узле остаётся воздух.

    Прогон 8f420f2c6621: плитки 4 × 2,5 см, подпись в две строки мелким кеглем
    посередине — узел почти пуст. То же правило, что для показателей (#87) и свободного
    текста (#77): подписи растут по шкале шаблона, пока занимают меньше половины узла
    и каждое слово встаёт в строку целиком. Потолок — ступень под заголовком: подпись
    схемы вровень с заголовком слайда спорила бы с ним.
    """
    if not available or (result.required_cy_emu or 0) >= FREE_BLOCK_FILL_SHARE * available:
        return result

    title_pt = _step_for(TextRole.TITLE, manifest).size_pt
    cap = next_size_down(manifest, title_pt) or title_pt
    best = result
    size = next_size_up(manifest, result.final_size_pt)
    while size is not None and size <= cap:
        fits, lines, required = measured(size)
        if not fits:
            break
        best = FitResult(
            final_size_pt=size, overflow=False, lines=lines,
            required_cy_emu=required, strategy=GROW,
        )
        if required >= FREE_BLOCK_FILL_SHARE * available:
            break
        size = next_size_up(manifest, size)
    return best


def fit_boxed(
    block: BoxedBlock,
    box: BBox,
    manifest: TemplateManifest,
    design: DesignRules,
    *,
    fonts: FontLibrary | None = None,
) -> FitResult:
    """Цитата или callout: кегль текста от ступени дизайн-системы вниз по шкале.

    Меряется всё, что встанет в рамку текста справа от полосы: подпись вида у callout,
    сам текст и строку автора у цитаты. `final_size_pt` — кегль текста; подпись вида
    идёт тем же кеглем, строка автора — кеглем подписи, но не крупнее текста.
    Не растёт: кегль цитаты — решение дизайн-системы, а место вокруг неё — воздух.
    Ниже порога читаемости (RG35) не спускается: не влезло — сокращение в узле `fit`.
    """
    style = style_of(block, design)
    step = _step_for(style.role, manifest)
    font = _font_of(step, manifest)
    frame = text_frame(box, style)
    available = usable_height_emu(frame)
    spacing = step.line_spacing or 1.0

    def measured(size_pt: float) -> tuple[int, int]:
        lines, required = 0, 0
        for paragraph in paragraphs(block, style, size_pt, bold=step.bold):
            m = measure_text(
                paragraph.text, font_family=font, size_pt=paragraph.size_pt, box=frame,
                line_spacing=spacing, bold=paragraph.bold, italic=step.italic, fonts=fonts,
            )
            lines += m.lines
            required += m.height_emu
        return lines, required

    size, lines, required = style.text_pt, 0, 0
    for size in _sizes(
        manifest, style.text_pt, allow_shrink=True, min_pt=design.reading_floor_pt
    ):
        lines, required = measured(size)
        if required <= available:
            return _fits(size, style.text_pt, lines, required)
    return _overflow(size, lines, required, available, splittable=False)


def fit_icon_list(
    block: BulletsBlock,
    box: BBox,
    manifest: TemplateManifest,
    design: DesignRules,
    *,
    fonts: FontLibrary | None = None,
) -> FitResult:
    """Иконочный список: кегль по шкале, текст меряется в рамке без колонки иконок.

    Колонка зависит от кегля (сторона иконки — один em), поэтому рамка считается заново
    на каждой ступени. Правила те же, что у свободного списка (`fit_block`): вниз по шкале,
    пока не влезет, и вверх до ступени под заголовком, пока занята меньше половины рамки.
    Вниз — не ниже порога читаемости (RG35): не влезло — сокращение пунктов и хвоста в узле.
    """
    step = _step_for(block.role, manifest)
    font = _font_of(step, manifest)
    spacing = step.line_spacing or 1.0
    available = usable_height_emu(box)
    text = "\n".join(item.text for item in block.items)

    def measured(size_pt: float) -> tuple[int, int]:
        frame = icon_text_frame(box, icon_column(box, size_pt, design))
        m = measure_text(
            text, font_family=font, size_pt=size_pt, box=frame, line_spacing=spacing,
            bold=step.bold, italic=step.italic, fonts=fonts,
        )
        return m.lines, m.height_emu

    start = block.size_pt or step.size_pt
    size, lines, required = start, 0, 0
    for size in _sizes(manifest, start, allow_shrink=True, min_pt=design.reading_floor_pt):
        lines, required = measured(size)
        if required <= available:
            break
    else:
        return _overflow(size, lines, required, available, len(block.items) > 1)

    best = _fits(size, start, lines, required)
    if block.size_pt is not None:
        return best
    title_pt = _step_for(TextRole.TITLE, manifest).size_pt
    cap = next_size_down(manifest, title_pt) or title_pt
    grow = next_size_up(manifest, size)
    while (
        grow is not None and grow <= cap
        and (best.required_cy_emu or 0) < FREE_BLOCK_FILL_SHARE * available
    ):
        lines, required = measured(grow)
        if required > available:
            break
        best = FitResult(
            final_size_pt=grow, overflow=False, lines=lines,
            required_cy_emu=required, strategy=GROW,
        )
        grow = next_size_up(manifest, grow)
    return best


def _box_for(block: TextBlock | BulletsBlock, layout: LayoutSpec) -> BBox:
    if block.bbox is not None:
        return block.bbox
    if block.placeholder_idx is None:
        raise LayoutFitError(f"блок {block.block_id}: нет ни координат, ни плейсхолдера")
    placeholder = layout.placeholder(block.placeholder_idx)
    if placeholder is None:
        raise LayoutFitError(
            f"блок {block.block_id}: в макете {layout.layout_id} нет плейсхолдера "
            f"idx={block.placeholder_idx}"
        )
    return placeholder.bbox


def _holds_a_line(box: BBox, size_pt: float, line_spacing: float | None) -> bool:
    """Помещается ли в рамку по высоте хотя бы одна строка этого кегля."""
    return usable_height_emu(box) >= round(line_height_emu(size_pt, line_spacing or 1.0))


def _band_holds_the_role_size(box: BBox, step: TypographyStep) -> bool:
    """Помещается ли в рамку хотя бы одна строка кеглем роли.

    Правило «заголовок не уменьшается» защищает иерархию: заголовок крупнее тела,
    и жертвовать этим ради лишнего слова нельзя. Но когда ограничивает **рамка**,
    а не текст — полоса заголовка ниже одной строки, — сокращать нечего: на VK WorkSpace
    так обрезались многоточием 7 заголовков из 12 (прогон 80e7af41ab54).
    """
    return _holds_a_line(box, step.size_pt, step.line_spacing)


def _title_size_floor(manifest: TemplateManifest, step: TypographyStep) -> float:
    """Ниже какого кегля заголовок не опускается: ближайшая ступень **крупнее** тела.

    Задача A9. Полоса заголовка VK Tech — 2,1 см: одна строка 24-м кеглем в неё влезает,
    две (2,03 см плюс поля рамки) — уже нет. `_band_holds_the_role_size` при этом истинно,
    кегль считался неприкосновенным, и заголовок резался по словам до 14–17 знаков:
    «ИИ пишет, но не…» не говорит ничего — а ради вывода заголовок и писался.
    На VK Education полоса держала медианно 7 знаков, а планировщику называлось 25.

    Ступень шкалы дешевле половины вывода. Но не любая: заголовок кеглем тела — это уже
    не заголовок, поэтому пол — ближайшая ступень **строго крупнее** тела. Шкала своя
    у каждого шаблона, никаких величин здесь нет (ADR-002). Если крупнее тела ступеней
    нет, пола нет и кегль остаётся прежним.
    """
    body = manifest.typography(TextRole.BODY)
    if body is None:
        return step.size_pt
    above = [size for size in manifest.size_ladder_pt if size > body.size_pt]
    return min(above) if above else step.size_pt


def _text_of(block: TextBlock | BulletsBlock) -> str:
    return block.text if isinstance(block, TextBlock) else "\n".join(i.text for i in block.items)


def _floor_of(
    block: TextBlock | BulletsBlock, box: BBox, step: TypographyStep, manifest: TemplateManifest
) -> float | None:
    """Ниже какого кегля заголовок не спускается; `None` — спуск по всей шкале.

    Заголовок уступает кегль, но по-разному. Полоса ниже строки кеглем роли — спуск
    по всей шкале (так было до A9: сокращать в таком заголовке нечего). Полоса, которая
    держит строку, но не две, — спуск до кегля тела и не ниже.

    Порог читаемости (RG35) — не здесь: `fit_text` берёт наибольшее из него и этого пола.
    Кегль старта ни один из них не поднимает (`_sizes`): кегль автора ниже порога остаётся
    кеглем автора и дальше не спускается.
    """
    if block.role is TextRole.TITLE and _band_holds_the_role_size(box, step):
        return _title_size_floor(manifest, step)
    return None


def fit_block(
    block: TextBlock | BulletsBlock,
    layout: LayoutSpec,
    manifest: TemplateManifest,
    *,
    fonts: FontLibrary | None = None,
    design: DesignRules | None = None,
) -> FitResult:
    """Вписывает текстовый блок: кегль и гарнитура — из типошкалы его роли.

    Иконочный список (свободный) меряется по рамке без колонки иконок: `fit_icon_list`.
    `design` нужен ему и даёт порог читаемости текстовому блоку; не передан — ДС считается
    из манифеста, порог — умолчание `READING_FLOOR_PT`."""
    if isinstance(block, BulletsBlock) and draws_icons(block):
        return fit_icon_list(
            block, block.bbox, manifest,  # type: ignore[arg-type]
            design if design is not None else DesignRules(manifest), fonts=fonts,
        )
    step = _step_for(block.role, manifest)
    box = _box_for(block, layout)
    floor = design.reading_floor_pt if design is not None else READING_FLOOR_PT
    result = _fit_text_block(block, box, manifest, fonts=fonts, reading_floor_pt=floor)
    if _grows_to_its_space(block, result):
        return _grown(
            result,
            text=_text_of(block),
            box=box,
            manifest=manifest,
            font_family=_font_of(step, manifest),
            bold=step.bold,
            italic=step.italic,
            line_spacing=step.line_spacing or 1.0,
            fonts=fonts,
        )
    return result


def _grows_to_its_space(block: TextBlock | BulletsBlock, result: FitResult) -> bool:
    """Растёт ли этот блок, если места ему дали больше, чем нужно тексту.

    Заголовок задаёт иерархию слайда и не растёт вовсе; блок, которому кегль назначили
    явно (`size_pt`), тоже не трогается — его назначили не просто так. Переполненному
    блоку расти некуда по определению.

    В плейсхолдере растёт только **тело**. Прежде не рос никакой: кегль плейсхолдера
    считался решением автора шаблона. Но вниз мы его и так меняем, когда текст не влезает
    (`allow_shrink`), и шаблоны кейса это прямо разрешают, помечая тело `normAutofit`;
    асимметрия «вниз можно, вверх нельзя» ничем не обоснована. Три пункта в теле
    на пол-слайда так и оставались кеглем роли (VK Education, прогон 6b1d9e82b612).
    Подпись, колонтитул и прочие полосы в рост не идут: их кегль несёт иерархию, а не
    объём текста, и у VK Education подпись под фото — полоса высотой ровно в строку.
    """
    if block.role is TextRole.TITLE or block.size_pt is not None or result.overflow:
        return False
    return block.placeholder_idx is None or block.role is TextRole.BODY


def _grown(
    result: FitResult,
    *,
    text: str,
    box: BBox,
    manifest: TemplateManifest,
    font_family: str,
    bold: bool,
    italic: bool,
    line_spacing: float,
    fonts: FontLibrary | None,
) -> FitResult:
    """Поднимает кегль по шкале шаблона, пока блок не займёт свою рамку.

    Потолок — ступень **под** заголовком этого шаблона: тело, набранное вровень
    с заголовком, стирает иерархию не хуже, чем тело крупнее него. Ни одной константы:
    и шкала, и потолок берутся из манифеста.
    """
    available = usable_height_emu(box)
    required = result.required_cy_emu or 0
    if not available or required >= FREE_BLOCK_FILL_SHARE * available:
        return result

    title_pt = _step_for(TextRole.TITLE, manifest).size_pt
    cap = next_size_down(manifest, title_pt) or title_pt
    best = result
    size = next_size_up(manifest, result.final_size_pt)
    while size is not None and size <= cap:
        m = measure_text(
            text, font_family=font_family, size_pt=size, box=box,
            line_spacing=line_spacing, bold=bold, italic=italic, fonts=fonts,
        )
        if m.height_emu > available:
            break
        best = FitResult(
            final_size_pt=size, overflow=False, lines=m.lines,
            required_cy_emu=m.height_emu, strategy=GROW,
        )
        if m.height_emu >= FREE_BLOCK_FILL_SHARE * available:
            break
        size = next_size_up(manifest, size)
    return best


@dataclass(frozen=True, slots=True)
class _ZoneFrame:
    """Что о зоне рецепта известно вписыванию: размер рамки, кегль и гарнитура примера."""

    box: BBox
    size_pt: float | None
    font_family: str | None


def _zone_frames(
    slide: SlideIR, manifest: TemplateManifest, rules: DesignRules
) -> dict[str, _ZoneFrame]:
    """Зоны рецепта слайда, у которых рамка известна целиком.

    Меряется только размер рамки: где она стоит на слайде, вписыванию не важно, а `x`, `y`
    у фигуры примера бывают отрицательными (заведена за край) — `BBox` таких не держит.
    Рамка при этом не копируется ни в блок, ни в зону: её задал автор шаблона.
    Рецепта нет в каталоге или у зоны нет рамки (каталог до RG18) — зоны нет в ответе.

    Гарнитура — у фигуры-примера по `Zone.xml_id` (D01, §10а): зона набрана так, как её
    набрал автор, а не так, как набрана роль. Фигуры не нашлось — гарнитура роли.

    Высота — не своя, а **до ближайшей зоны под собой** (RG39). Рамки зон в шаблоне
    перекрываются: у WorkSpace рамка заголовка тянется до 1 592 263 EMU, а зона тела
    начинается с 1 243 208. Пока заголовок был в одну строку, нижняя часть его рамки
    пустовала, и перекрытие никому не мешало. Заголовок в две строки её занимает —
    и накрывает первую строку тела (превью s05 прогона `ae907ce14a7d`).
    """
    recipe = next((r for r in rules.ds.recipes if r.recipe_id == slide.recipe_id), None)
    if recipe is None:
        return {}
    example = next(
        (e for e in manifest.examples if e.slide_index == recipe.example_index), None
    )
    fonts = {
        shape.xml_id: shape.font_family
        for shape in (example.shapes if example is not None else [])
        if shape.xml_id is not None
    }
    framed = [zone for zone in recipe.zones if zone.has_frame and zone.cx and zone.cy]
    frames: dict[str, _ZoneFrame] = {}
    for zone in framed:
        frames[zone.zone_id] = _ZoneFrame(
            box=BBox(x=0, y=0, cx=zone.cx or 0, cy=_room_below(zone, framed)),
            size_pt=zone.size_pt,
            font_family=fonts.get(zone.xml_id) if zone.xml_id is not None else None,
        )
    return frames


def _room_below(zone: Zone, others: list[Zone]) -> int:
    """Высота, которой зона располагает на самом деле: до ближайшей зоны под собой.

    Зоны — это фигуры автора шаблона, и рамки у них перекрываются: текст в них короче
    рамок, и автору это не мешало. Нам мешает: текст, занявший свою рамку целиком,
    ложится на соседа снизу.

    Сосед считается соседом, только если перекрывается по ширине: две колонки рядом
    друг другу не мешают, как бы ни стояли по вертикали. Перекрытие меньше доли
    `_NEIGHBOUR_OVERLAP_SHARE` ширины меньшей из двух зон — тоже не соседство (D07):
    волосок раскладки урезал бы рамку ниже строки её кегля и делал её якорем.
    Если сосед начинается выше низа зоны, высота урезается до расстояния между их
    верхами — ровно до того, что зоне принадлежит без спора.
    """
    top, height = zone.y or 0, zone.cy or 0
    left, width = zone.x or 0, zone.cx or 0

    def overlap(other: Zone) -> int:
        start, end = other.x or 0, (other.x or 0) + (other.cx or 0)
        return min(left + width, end) - max(left, start)

    below = [
        other.y
        for other in others
        if other is not zone
        and other.y is not None
        and other.y > top
        and other.y < top + height
        # Перекрытие по ширине: иначе это соседняя колонка, а не сосед снизу.
        and overlap(other) > 0
        and overlap(other) >= _NEIGHBOUR_OVERLAP_SHARE * min(width, other.cx or 0)
    ]
    return min([height, *[value - top for value in below if value is not None]])


def _fit_text_block(
    block: TextBlock | BulletsBlock,
    box: BBox,
    manifest: TemplateManifest,
    *,
    fonts: FontLibrary | None,
    zone: _ZoneFrame | None = None,
    reading_floor_pt: float = READING_FLOOR_PT,
) -> FitResult:
    """Текстовый блок в своей рамке — плейсхолдера, координат или зоны рецепта.

    Кегль блока (его ставит `_titles_yield_size`) главнее всего; дальше — кегль зоны,
    дальше — кегль роли. Кегль зоны — значение автора из файла, как у плейсхолдера:
    стартует как есть, даже вне шкалы, и строка этого кегля в рамке — его решение
    (`author_start`). Ступени вниз — только по шкале. Заголовок уступает кегль по одному
    правилу и в плейсхолдере, и в зоне (`_floor_of`). Рост — не здесь: зона не растёт
    вовсе, её размер и кегль задал автор шаблона (см. `fit_block` и `_grown`).

    Рамка зоны, в которую не встаёт ни одна строка **её собственного** кегля, — якорь,
    а не коробка (D02, §11): ограничивает только ширина. Мерить её по высоте — снять
    весь текст, который у автора в ней растёт вниз (карточки VK Tech, рамки 12–13 pt).
    Спуск кегля в зоне — не дальше `_ZONE_STEPS_DOWN` ступеней, дальше — сокращение.
    И в зоне, и вне её — не ниже порога читаемости (RG35): ступень под ним не берётся,
    текст сокращается; исключение — блок, который сокращение свело бы к нулю (D06, `fit_text`).
    """
    step = _step_for(block.role, manifest)
    zone_pt = zone.size_pt if zone is not None else None
    return fit_text(
        _text_of(block),
        box=box,
        manifest=manifest,
        start_size_pt=block.size_pt or zone_pt or step.size_pt,
        font_family=(zone.font_family if zone is not None else None) or _font_of(step, manifest),
        min_size_pt=_floor_of(block, box, step, manifest),
        reading_floor_pt=reading_floor_pt,
        bold=step.bold,
        italic=step.italic,
        line_spacing=step.line_spacing or 1.0,
        fonts=fonts,
        author_start=block.size_pt is None and zone_pt is not None,
        words_bold=zone is not None,
        anchor=zone_pt is not None and not _holds_a_line(box, zone_pt, step.line_spacing),
        max_steps=_ZONE_STEPS_DOWN if zone is not None else None,
    )


def fit_slide(
    slide: SlideIR,
    manifest: TemplateManifest,
    *,
    fonts: FontLibrary | None = None,
    content: ContentPackage | None = None,
    design: DesignRules | None = None,
    by_example: bool = False,
) -> SlideIR:
    """Возвращает слайд с заполненным `fit_report` по текстовым блокам, таблицам, KPI,
    составным компонентам, цитатам и callout. Неподдерживаемый паттерн не вписывается:
    писатель заменит его буллетами и впишет их сам.

    `by_example` — путь сборки по примерам (change 5б `no-example-goes-by-design`): слайд без
    примера верстается дизайн-системой, и схема любого паттерна вписывается по своей
    раскладке, а не ждёт замены списком. По умолчанию — прежний путь.

    `design` — ответы дизайн-системы (DG3). Узел `fit` передаёт их из состояния графа;
    без них они считаются из манифеста здесь же.

    Блок с `zone_id` меряется по рамке своей зоны из рецепта слайда (`design.ds.recipes`,
    RG29): рамки слайду по рецепту задаёт рецепт, а не макет. Зона не нашлась или без
    рамки — блок без записи в `fit_report`, как было до RG29: старые каталоги и чекпойнты
    читаются. Макет нужен только блокам вне зон — слайд по рецепту
    (`SlideIR.by_recipe`, все блоки в зонах) вписывается и без него."""
    rules = design if design is not None else DesignRules(manifest)
    report: dict[str, FitResult] = {}
    frames = _zone_frames(slide, manifest, rules)
    for block in slide.blocks:
        if block.zone_id is None or not isinstance(block, TextBlock | BulletsBlock):
            continue
        if (zone := frames.get(block.zone_id)) is not None:
            report[block.block_id] = _fit_text_block(
                block, zone.box, manifest, fonts=fonts, zone=zone,
                reading_floor_pt=rules.reading_floor_pt,
            )

    if slide.by_recipe:
        return slide.model_copy(update={"fit_report": report})
    layout = manifest.layout(slide.layout_id)
    if layout is None:
        raise LayoutFitError(f"слайд {slide.slide_id}: макета {slide.layout_id} нет в манифесте")
    outside = [block for block in slide.blocks if block.zone_id is None]
    patterns = buildable_patterns(slide, by_example=by_example)
    for block in outside:
        if isinstance(block, TextBlock | BulletsBlock):
            report[block.block_id] = fit_block(
                block, layout, manifest, fonts=fonts, design=rules
            )
        elif isinstance(block, SmartArtBlock):
            if block.pattern not in patterns:
                continue
            if block.bbox is None:
                raise LayoutFitError(f"блок {block.block_id}: smartart требует координат")
            report[block.block_id] = fit_smartart(
                block, block.bbox, manifest, fonts=fonts, design=rules,
                # Перенос шагов в несколько рядов — только на пути по примерам: прежний
                # закреплён эталонами XML и меняться не должен.
                by_example=goes_by_design(slide, by_example=by_example),
            )
        elif isinstance(block, QuoteBlock | CalloutBlock):
            if block.bbox is None:
                raise LayoutFitError(f"блок {block.block_id}: {block.type} требует координат")
            report[block.block_id] = fit_boxed(block, block.bbox, manifest, rules, fonts=fonts)
        elif isinstance(block, TableBlock | KpiBlock):
            box = block.bbox
            if box is None:
                raise LayoutFitError(f"блок {block.block_id}: {block.type} требует координат")
            if isinstance(block, TableBlock):
                dataset = (
                    content.dataset(block.dataset_ref)
                    if content is not None and block.dataset_ref
                    else None
                )
                report[block.block_id] = fit_table(
                    block, box, manifest, dataset=dataset, fonts=fonts,
                    reading_floor_pt=rules.reading_floor_pt,
                )
            else:
                report[block.block_id] = fit_kpi(
                    block, box, manifest, fonts=fonts, sizes=rules.kpi_sizes()
                )
    return slide.model_copy(update={"fit_report": report})
