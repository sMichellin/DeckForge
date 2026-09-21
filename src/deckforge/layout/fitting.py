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

from collections.abc import Iterator
from typing import Any

from deckforge.domain.base import BBox
from deckforge.domain.content import ContentPackage, Dataset
from deckforge.domain.enums import TextRole
from deckforge.domain.rules import next_size_down, next_size_up
from deckforge.domain.slide import (
    BulletsBlock,
    FitResult,
    KpiBlock,
    SlideIR,
    SmartArtBlock,
    TableBlock,
    TextBlock,
)
from deckforge.domain.template import LayoutSpec, TemplateManifest, TypographyStep
from deckforge.domain.units import TEXT_FRAME_INSET_Y_EMU
from deckforge.layout.diagram import SUPPORTED_PATTERNS, diagram_geometry
from deckforge.layout.errors import LayoutFitError
from deckforge.layout.fonts import FontLibrary
from deckforge.layout.metrics import (
    line_height_emu,
    measure_text,
    split_paragraphs,
    usable_height_emu,
)
from deckforge.layout.tabular import table_cells, table_has_header

__all__ = [
    "LayoutFitError",
    "fit_block",
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

#: Ниже этой доли своей рамки свободный блок теряется в пустоте: текст жмётся к верхнему
#: краю, а остальное поле остаётся белым. Прогон 693d464d54fb: четыре строки в рамке
#: высотой двенадцать сантиметров — слайд выглядит пустым, хотя переполнения нет.
FREE_BLOCK_FILL_SHARE = 0.5


def _sizes(manifest: TemplateManifest, start_pt: float, allow_shrink: bool) -> Iterator[float]:
    """Кегли для перебора: старт, привязанный к шкале шаблона, и ступени вниз."""
    ladder = manifest.size_ladder_pt
    size: float | None = start_pt
    if ladder and start_pt not in ladder:
        # Кегль вне шкалы шаблона не используется даже как стартовый (ADR-002).
        size = next_size_down(manifest, start_pt) or min(ladder)
    while size is not None:
        yield size
        size = next_size_down(manifest, size) if allow_shrink else None


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
    bold: bool = False,
    italic: bool = False,
    line_spacing: float = 1.0,
    fonts: FontLibrary | None = None,
) -> FitResult:
    """Подбирает кегль по шкале шаблона; не влезло на нижней ступени — назначает стратегию."""
    available = usable_height_emu(box)
    size, lines, required = start_size_pt, 0, 0
    for size in _sizes(manifest, start_size_pt, allow_shrink):
        m = measure_text(
            text, font_family=font_family, size_pt=size, box=box,
            line_spacing=line_spacing, bold=bold, italic=italic, fonts=fonts,
        )
        lines, required = m.lines, m.height_emu
        if required <= available:
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
) -> FitResult:
    """Таблица с колонками равной ширины: высота строки — самая высокая ячейка.

    Поля ячейки PowerPoint по умолчанию совпадают с полями текстовой рамки, поэтому ячейка
    меряется как рамка шириной в колонку. Кегль — от роли `body` вниз по шкале шаблона.
    """
    step = _step_for(TextRole.BODY, manifest)
    rows_count = len(table_cells(block, dataset))
    size, lines, required = step.size_pt, 0, 0
    for size in _sizes(manifest, step.size_pt, allow_shrink=True):
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
) -> FitResult:
    """Показатели колонками: значение — одной строкой от кегля `subtitle` вниз по шкале,
    подпись — кеглем `caption`. `final_size_pt` — кегль значения."""
    value_step = manifest.typography(TextRole.SUBTITLE) or _step_for(TextRole.BODY, manifest)
    label_step = manifest.typography(TextRole.CAPTION) or _step_for(TextRole.BODY, manifest)
    column = BBox(x=box.x, y=box.y, cx=max(1, box.cx // len(block.items)), cy=box.cy)
    available = usable_height_emu(box)

    def measured(size_pt: float) -> tuple[bool, int, int]:
        """(значение в одну строку, строк всего, нужная высота) при этом кегле."""
        one_line, lines, required = True, 0, 0
        for item in block.items:
            value = measure_text(item.value, font_family=_font_of(value_step, manifest),
                                 size_pt=size_pt, box=column, bold=value_step.bold, fonts=fonts)
            label = measure_text(item.label, font_family=_font_of(label_step, manifest),
                                 size_pt=label_step.size_pt, box=column, fonts=fonts)
            one_line = one_line and value.lines <= 1
            lines = max(lines, value.lines + label.lines)
            required = max(required, value.height_emu + label.height_emu)
        return one_line, lines, required

    size, lines, required = value_step.size_pt, 0, 0
    for size in _sizes(manifest, value_step.size_pt, allow_shrink=True):
        one_line, lines, required = measured(size)
        if one_line and required <= available:
            return _grown_kpi(
                _fits(size, value_step.size_pt, lines, required), measured, manifest, available
            )
    return _overflow(size, lines, required, available, splittable=False)


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
        one_line, lines, required = measured(size)
        if not one_line or required > available:
            break
        best = FitResult(
            final_size_pt=size, overflow=False, lines=lines,
            required_cy_emu=required, strategy=GROW,
        )
        if required >= FREE_BLOCK_FILL_SHARE * available:
            break
        size = next_size_up(manifest, size)
    return best


def fit_smartart(
    block: SmartArtBlock,
    box: BBox,
    manifest: TemplateManifest,
    *,
    fonts: FontLibrary | None = None,
) -> FitResult:
    """Все подписи компонента одним кеглем: от `body` вниз по шкале, пока каждая не влезет
    в свою рамку из `diagram_geometry`. Разный кегль у соседних шагов выглядит ошибкой.

    Рамки узлов узкие, и слово в них рвётся по знакам: высота при этом влезает, но «Прове/рка»
    в узле — брак вёрстки. Поэтому подпись влезла, только если и каждое её слово встало
    в строку целиком."""
    step = _step_for(TextRole.BODY, manifest)
    font = _font_of(step, manifest)
    labels = diagram_geometry(block.pattern, len(block.items), box).labels
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

    size, lines, required = step.size_pt, 0, 0
    for size in _sizes(manifest, step.size_pt, allow_shrink=True):
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


def _band_holds_the_role_size(box: BBox, step: TypographyStep) -> bool:
    """Помещается ли в рамку хотя бы одна строка кеглем роли.

    Правило «заголовок не уменьшается» защищает иерархию: заголовок крупнее тела,
    и жертвовать этим ради лишнего слова нельзя. Но когда ограничивает **рамка**,
    а не текст — полоса заголовка ниже одной строки, — сокращать нечего: на VK WorkSpace
    так обрезались многоточием 7 заголовков из 12 (прогон 80e7af41ab54).
    """
    line = round(line_height_emu(step.size_pt) * (step.line_spacing or 1.0))
    return usable_height_emu(box) >= line


def fit_block(
    block: TextBlock | BulletsBlock,
    layout: LayoutSpec,
    manifest: TemplateManifest,
    *,
    fonts: FontLibrary | None = None,
) -> FitResult:
    """Вписывает текстовый блок: кегль и гарнитура — из типошкалы его роли."""
    step = _step_for(block.role, manifest)
    text = block.text if isinstance(block, TextBlock) else "\n".join(i.text for i in block.items)
    box = _box_for(block, layout)
    shrinkable = block.role is not TextRole.TITLE or not _band_holds_the_role_size(box, step)
    font_family = _font_of(step, manifest)
    line_spacing = step.line_spacing or 1.0
    result = fit_text(
        text,
        box=box,
        manifest=manifest,
        start_size_pt=block.size_pt or step.size_pt,
        font_family=font_family,
        allow_shrink=shrinkable,
        bold=step.bold,
        italic=step.italic,
        line_spacing=line_spacing,
        fonts=fonts,
    )
    if _grows_to_its_space(block, result):
        return _grown(
            result,
            text=text,
            box=box,
            manifest=manifest,
            font_family=font_family,
            bold=step.bold,
            italic=step.italic,
            line_spacing=line_spacing,
            fonts=fonts,
        )
    return result


def _grows_to_its_space(block: TextBlock | BulletsBlock, result: FitResult) -> bool:
    """Растёт ли этот блок, если места ему дали больше, чем нужно тексту.

    Растёт только свободный блок с основным текстом. Плейсхолдер — решение автора
    шаблона, и его кегль наш; заголовок задаёт иерархию слайда и не растёт вовсе;
    блок, которому кегль назначили явно (`size_pt`), тоже не трогается — его назначили
    не просто так. Переполненному блоку расти некуда по определению.
    """
    return (
        block.placeholder_idx is None
        and block.role is not TextRole.TITLE
        and block.size_pt is None
        and not result.overflow
    )


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


def fit_slide(
    slide: SlideIR,
    manifest: TemplateManifest,
    *,
    fonts: FontLibrary | None = None,
    content: ContentPackage | None = None,
) -> SlideIR:
    """Возвращает слайд с заполненным `fit_report` по текстовым блокам, таблицам, KPI
    и составным компонентам. Неподдерживаемый паттерн не вписывается: писатель заменит его
    буллетами и впишет их сам."""
    layout = manifest.layout(slide.layout_id)
    if layout is None:
        raise LayoutFitError(f"слайд {slide.slide_id}: макета {slide.layout_id} нет в манифесте")
    report: dict[str, FitResult] = {}
    for block in slide.blocks:
        if isinstance(block, TextBlock | BulletsBlock):
            report[block.block_id] = fit_block(block, layout, manifest, fonts=fonts)
        elif isinstance(block, SmartArtBlock):
            if block.pattern not in SUPPORTED_PATTERNS:
                continue
            if block.bbox is None:
                raise LayoutFitError(f"блок {block.block_id}: smartart требует координат")
            report[block.block_id] = fit_smartart(block, block.bbox, manifest, fonts=fonts)
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
                    block, box, manifest, dataset=dataset, fonts=fonts
                )
            else:
                report[block.block_id] = fit_kpi(block, box, manifest, fonts=fonts)
    return slide.model_copy(update={"fit_report": report})
