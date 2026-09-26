"""Каталог композиций шаблона. Change `recipes-in-the-design-system`, таск 03a.

Слайд-пример — это решение автора шаблона, принятое целиком: где плашка, где декор,
где картинка и где текст. Остальные разделы дизайн-системы описывают шаблон по частям
(цвета, лестница, сетка, компоненты); здесь описывается **композиция**.

Замер DS1: вне плейсхолдеров стоит 96 % содержимого примеров у VK Tech, 91 %
у VK WorkSpace, 87 % у VK Education. То есть оформление шаблона живёт в примерах,
а не в макетах, и повторить его можно только взяв пример целиком.

Ни одного числа конкретного шаблона: область контента — поля сетки, ячейка повтора —
доли компонента, «крупно» — ступени лестницы этого же шаблона.
"""

from __future__ import annotations

from itertools import pairwise

from deckforge.designsystem.models import (
    DesignSystem,
    Origin,
    Recipe,
    RecipeKind,
    TypeLevel,
    Zone,
)
from deckforge.domain.enums import LayoutKind, TextRole
from deckforge.domain.template import (
    ComponentKind,
    ComponentSpec,
    ExampleShape,
    ShapeKind,
    TemplateExample,
    TemplateManifest,
)
from deckforge.domain.units import EMU_PER_PT, TEXT_FRAME_INSET_X_EMU, TEXT_FRAME_INSET_Y_EMU

#: Средняя ширина знака и высота строки в долях кегля. Те же величины, что у плейсхолдеров
#: (`parsing/capacity.py`): вместимость зоны и вместимость плейсхолдера обязаны мериться
#: одинаково, иначе композиция получит два разных лимита на одно и то же место. Слой
#: `designsystem` стоит ниже `parsing` и импортировать его не может, поэтому величины
#: продублированы, а тест сверяет их с оригиналом.
CHAR_WIDTH_RATIO = 0.52
LINE_HEIGHT_RATIO = 1.2

#: Текст короче этого — не абзац, а число или метка. Порог алгоритма: «1 275», «+12 %»,
#: «3,5×» укладываются, любое предложение — нет.
NUMBER_TEXT_LEN = 8

#: Доля области контента, начиная с которой фигура считается крупной. Одна планка
#: и для текстовой зоны, и для картинки: «крупное» на слайде — это треть содержательной
#: области, и разводить два порога незачем. Без планки «текстом с картинкой» становится
#: каждый пример, где в углу стоит логотип или иконка.
LARGE_ZONE_SHARE = 1 / 3

#: Допуск, в пределах которого рамка считается ячейкой компонента: доля размера ячейки.
#: Порог алгоритма того же порядка, что допуск 2,5 % при поиске самих компонентов
#: (`parsing/components.py`).
CELL_TOLERANCE = 0.1

#: Верхняя треть слайда: там стоит заголовок, если он не попал в плейсхолдер.
TOP_BAND_SHARE = 1 / 3

#: Сколько текстовых зон бывает у структурного слайда: заголовок и подзаголовок.
#: Больше — это уже содержательный слайд, как бы ни был классифицирован его макет.
STRUCTURAL_ZONES = 2

#: Вид макета примера → вид рецепта. Структурные слайды колоды берут рецепт своего вида,
#: и решает это макет, а не фигуры: обложка шаблона остаётся обложкой, даже если автор
#: нарисовал на ней карточки.
STRUCTURAL_KINDS: dict[LayoutKind, RecipeKind] = {
    LayoutKind.TITLE: RecipeKind.COVER,
    LayoutKind.SECTION: RecipeKind.SECTION,
    LayoutKind.CLOSING: RecipeKind.FINAL,
}

#: Заказ плана (`SlidePlan.suggested_visual`) → вид рецепта. Одна таблица на все шаблоны:
#: её читают меню плана (05a) и подбор рецепта (05b), и разъехаться двум копиям негде.
#: Заказы `cards` и `text` добавляет в меню таск 05a — здесь они названы заранее, чтобы
#: соответствие жило в одном месте.
VISUAL_TO_KIND: dict[str, RecipeKind] = {
    "kpi": RecipeKind.METRICS,
    "image": RecipeKind.TEXT_WITH_PICTURE,
    "cards": RecipeKind.CARDS,
    "text": RecipeKind.TEXT,
}

#: Роль плейсхолдера → ступень лестницы. У плейсхолдера роль уже назначена макетом,
#: и переопределять её кеглем незачем.
ROLE_LEVELS: dict[TextRole, TypeLevel] = {
    TextRole.TITLE: TypeLevel.SLIDE_TITLE,
    TextRole.SUBTITLE: TypeLevel.SECTION_SUBTITLE,
    TextRole.BODY: TypeLevel.BODY,
    TextRole.CAPTION: TypeLevel.CAPTION,
}

#: Виды фигур, из-за которых пример в v1 рецептом не становится: диаграмму и таблицу
#: колода строит своими данными, а не текстом в чужую рамку (сужение зонтичного
#: предложения `slide-recipes`).
UNSUPPORTED_KINDS = frozenset({ShapeKind.CHART, ShapeKind.TABLE})


def _content_box(ds: DesignSystem) -> tuple[int, int, int, int]:
    """Область контента шаблона: прямоугольник внутри полей сетки."""
    grid = ds.grid
    return (
        grid.margins.left,
        grid.margins.top,
        grid.width_emu - grid.margins.right,
        grid.height_emu - grid.margins.bottom,
    )


def _center(shape: ExampleShape) -> tuple[int, int]:
    return shape.x + shape.cx // 2, shape.y + shape.cy // 2


def _inside(shape: ExampleShape, box: tuple[int, int, int, int]) -> bool:
    x, y = _center(shape)
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _is_text(shape: ExampleShape) -> bool:
    return shape.text_len > 0 or shape.kind is ShapeKind.TEXT


def _level_of(ds: DesignSystem, shape: ExampleShape) -> TypeLevel:
    """Ступень зоны: у плейсхолдера — роль макета, у свободной фигуры — ближайший кегль."""
    if shape.placeholder_idx is not None and shape.role is not None:
        return ROLE_LEVELS[shape.role]
    steps = ds.typography.steps
    size_pt = shape.size_pt
    if size_pt is None or not steps:
        return TypeLevel.BODY
    nearest = min(steps, key=lambda step: (abs(step.size_pt - size_pt), step.level.value))
    return nearest.level


def _size_of(ds: DesignSystem, shape: ExampleShape, level: TypeLevel) -> tuple[float | None, bool]:
    """Кегль зоны и своё ли это число.

    Своё — то, что стоит у автора: кегль прогона или кегль плейсхолдера из макета
    (`ExampleShape.size_pt`, RG42). Нет такого — берём ступень лестницы для роли,
    чтобы было чем считать вместимость, но **помечаем догадкой**: ставить её в файл
    нельзя, и писатель этого не сделает (D04).
    """
    if shape.size_pt is not None:
        return shape.size_pt, True
    guess = next((step.size_pt for step in ds.typography.steps if step.level is level), None)
    return guess, False


def _capacity(shape: ExampleShape, size_pt: float | None) -> int:
    """Сколько знаков держит рамка зоны. Считается как у плейсхолдеров шаблона."""
    if not size_pt or size_pt <= 0:
        return 0
    usable_cx = max(0, shape.cx - 2 * TEXT_FRAME_INSET_X_EMU)
    usable_cy = max(0, shape.cy - 2 * TEXT_FRAME_INSET_Y_EMU)
    char_width = size_pt * CHAR_WIDTH_RATIO * EMU_PER_PT
    line_height = size_pt * LINE_HEIGHT_RATIO * EMU_PER_PT
    if char_width <= 0 or line_height <= 0:
        return 0
    return max(0, int(usable_cx // char_width) * int(usable_cy // line_height))


def _component_of(manifest: TemplateManifest, example: TemplateExample) -> ComponentSpec | None:
    """Компонент шаблона, встреченный на этом примере. Их может быть несколько —
    берётся самый повторяемый: ряд карточек важнее пары подписей."""
    seen = [c for c in manifest.components if example.slide_index in c.seen_on]
    if not seen:
        return None
    return max(seen, key=lambda c: (c.repeats, c.width_share * c.height_share))


def _same_size(shapes: list[ExampleShape]) -> list[list[ExampleShape]]:
    """Разложить фигуры по размеру и кеглю: ячейки одного ряда одинаковы во всём.

    Кегль в условии затем, что заголовок и абзац под ним бывают одной ширины и высоты —
    и без него пара «заголовок + лид» читается как ряд из двух карточек. У настоящего
    ряда ступень лестницы у всех ячеек одна: автор набрал их одинаково.
    """
    buckets: list[list[ExampleShape]] = []
    for shape in sorted(shapes, key=lambda s: (-s.cx * s.cy, s.shape_id)):
        for bucket in buckets:
            first = bucket[0]
            if (
                shape.size_pt == first.size_pt
                and abs(shape.cx - first.cx) <= first.cx * CELL_TOLERANCE
                and abs(shape.cy - first.cy) <= first.cy * CELL_TOLERANCE
            ):
                bucket.append(shape)
                break
        else:
            buckets.append([shape])
    return buckets


def _even_line(cells: list[ExampleShape], *, horizontal: bool) -> tuple[list[ExampleShape], float]:
    """Ячейки с равным шагом по оси — и сам шаг. Шаг вразнобой рядом не считается:
    три случайно похожие фигуры по слайду не композиция автора."""
    line = sorted(cells, key=lambda s: _center(s)[0 if horizontal else 1])
    if len(line) < 2:
        return [], 0.0
    along = [_center(cell)[0 if horizontal else 1] for cell in line]
    steps = [b - a for a, b in pairwise(along)]
    step = float(steps[0])
    if step <= 0 or any(abs(other - step) > step * CELL_TOLERANCE for other in steps):
        return [], 0.0
    return line, step


def _lines_of(cells: list[ExampleShape], *, horizontal: bool) -> list[list[ExampleShape]]:
    """Разложить ячейки по линиям: ряд — это ячейки на одной высоте."""
    lines: list[list[ExampleShape]] = []
    across = cells[0].cy if horizontal else cells[0].cx
    for cell in sorted(cells, key=lambda s: _center(s)[1 if horizontal else 0]):
        line = _center(cell)[1 if horizontal else 0]
        if lines and abs(line - _center(lines[-1][0])[1 if horizontal else 0]) <= across / 2:
            lines[-1].append(cell)
        else:
            lines.append([cell])
    return lines


def _grid(cells: list[ExampleShape], *, horizontal: bool) -> list[ExampleShape]:
    """Сетка одинаковых ячеек в порядке чтения — или пусто, если это не сетка.

    Повтор бывает не только рядом: у VK Tech шесть карточек стоят 3×2, и ряд из трёх —
    это половина композиции. Половину вёрстка заполняет, вторую оставляет пустой
    и удалить не может: в `repeat_xml_ids` её нет. Поэтому повторами считается вся сетка.

    Сетка — это линии равной длины с равным шагом внутри. Три случайно похожие фигуры,
    разбросанные по слайду, ни линий равной длины, ни равного шага не дают.
    """
    lines = _lines_of(cells, horizontal=horizontal)
    if not lines or len({len(line) for line in lines}) != 1:
        return []
    #: Линии тоже стоят с равным шагом: иначе три одинаковые надписи, разбросанные
    #: по слайду, читаются как три «строки» сетки по одной ячейке.
    if len(lines) > 1 and not _even_line(
        [line[0] for line in lines], horizontal=not horizontal
    )[0]:
        return []
    ordered: list[ExampleShape] = []
    for line in lines:
        row, _step = _even_line(line, horizontal=horizontal)
        if len(line) > 1 and not row:
            return []
        ordered.extend(row or line)
    return ordered if len(ordered) >= 2 else []


def _row_in_the_example(ds: DesignSystem, example: TemplateExample) -> list[ExampleShape]:
    """Ряд повторов, найденный по самому примеру: ячейки, ряд горизонтален, шаг.

    Компонент шаблона (`manifest.components`) видит не всякий ряд: на обложке VK Tech
    пять одинаковых карточек не опознались ни одним компонентом, рецепт вышел «без
    повторов», и вёрстка оставила их пустыми — удалять нечего, `repeat_xml_ids` пуст.
    Одинаковые фигуры, стоящие по оси с равным шагом, — это и есть повтор, и увидеть
    его можно без парсера.

    Рамка, в которую не влезает ни одного знака самым мелким кеглем шаблона, ячейкой
    не считается: у той же обложки пять точек-индикатора по 0,27 см — декор автора,
    а не ряд карточек, и записать их в повторы значило бы обещать вёрстке место
    под текст там, где его нет.
    """
    holders = [
        shape
        for shape in example.shapes
        if shape.cx > 0 and shape.cy > 0 and _holds_a_character(shape, ds)
    ]
    best: list[ExampleShape] = []
    for bucket in _same_size(holders):
        if len(bucket) < 2:
            continue
        for horizontal in (True, False):
            cells = _grid(bucket, horizontal=horizontal)
            area = cells[0].cx * cells[0].cy if cells else 0
            better = len(cells) > len(best) or (
                len(cells) == len(best) and best and area > best[0].cx * best[0].cy
            )
            if cells and better:
                best = cells
    return best


def _holds_a_character(shape: ExampleShape, ds: DesignSystem) -> bool:
    """Влезает ли в рамку хоть один знак самым мелким кеглем шаблона."""
    smallest = min((step.size_pt for step in ds.typography.steps), default=0.0)
    return bool(smallest) and _capacity(shape, smallest) > 0


def _cells_to_repeats(
    example: TemplateExample,
    cells: list[ExampleShape],
    *,
    horizontal: bool,
    step: float,
    count: int,
) -> dict[str, int]:
    """Разложить фигуры примера по ячейкам ряда: и плашку, и её заголовок, и её текст.

    Ячейка — прямоугольник, поэтому проверок две. Без второй, поперёк оси, в средний
    повтор попадал заголовок слайда: он стоит над рядом, но отцентрован по его середине.
    Цена ошибки двойная — заголовок получал пункт списка вместо заголовка, а вёрстка
    удаляла его вместе с неиспользованным повтором.
    """
    if not cells or step <= 0:
        return {}
    origin = min(_center(cell)[0 if horizontal else 1] for cell in cells)
    half = (cells[0].cx if horizontal else cells[0].cy) / 2
    band_lo = min((cell.y if horizontal else cell.x) for cell in cells)
    band_hi = max(((cell.y + cell.cy) if horizontal else (cell.x + cell.cx)) for cell in cells)
    mapping: dict[str, int] = {}
    for shape in example.shapes:
        center = _center(shape)
        along, across = (center[0], center[1]) if horizontal else (center[1], center[0])
        if not band_lo <= across <= band_hi:
            continue
        index = round((along - origin) / step)
        if 0 <= index < count and abs(along - (origin + index * step)) <= half:
            mapping[shape.shape_id] = index
    return mapping


def _repeat_map(
    manifest: TemplateManifest, ds: DesignSystem, example: TemplateExample
) -> tuple[dict[str, int], int]:
    """Какая фигура в каком повторе стоит и сколько повторов в ряду.

    Начало ряда не хранится в компоненте, поэтому берётся из самого примера: рамки
    размером с ячейку выстраиваются вдоль оси, первая и задаёт отсчёт. Дальше в повтор N
    попадает всё, чей центр лежит в N-й ячейке, — и плашка, и её заголовок, и её текст.

    Ячейка — прямоугольник, поэтому проверок две. Без второй, поперёк оси, в средний
    повтор попадал заголовок слайда: он стоит над рядом, но отцентрован по его середине.
    Цена ошибки двойная — заголовок получал пункт списка вместо заголовка, а вёрстка
    удаляла его вместе с неиспользованным повтором.
    """
    component = _component_of(manifest, example)
    if component is None:
        return _by_the_example(ds, example)

    size = manifest.slide_size
    horizontal = component.axis == "row"
    cell_cx = component.width_share * size.cx_emu
    cell_cy = component.height_share * size.cy_emu
    step = component.gap_share * (size.cx_emu if horizontal else size.cy_emu)
    if step <= 0 or cell_cx <= 0 or cell_cy <= 0:
        return _by_the_example(ds, example)

    sized = [
        shape
        for shape in example.shapes
        if abs(shape.cx - cell_cx) <= cell_cx * CELL_TOLERANCE
        and abs(shape.cy - cell_cy) <= cell_cy * CELL_TOLERANCE
    ]
    cells = _row_of(sized, horizontal=horizontal, across=cell_cy if horizontal else cell_cx)
    if len(cells) < 2:
        return _by_the_example(ds, example)

    mapping = _cells_to_repeats(
        example, cells, horizontal=horizontal, step=step, count=component.repeats
    )
    return mapping, component.repeats


def _row_of(
    sized: list[ExampleShape], *, horizontal: bool, across: float
) -> list[ExampleShape]:
    """Ряд — это ячейки, стоящие на одной высоте, а не все рамки размером с ячейку.

    Рамка размером с ячейку бывает и вне ряда: заголовок такой же ширины, плашка внизу.
    Пустить её в отсчёт — значит растянуть полосу ряда на пол-слайда и забрать в повтор
    всё, что попало в неё по оси.
    """
    groups: list[list[ExampleShape]] = []
    for cell in sorted(sized, key=lambda s: _center(s)[1 if horizontal else 0]):
        line = _center(cell)[1 if horizontal else 0]
        if groups and abs(line - _center(groups[-1][0])[1 if horizontal else 0]) <= across / 2:
            groups[-1].append(cell)
        else:
            groups.append([cell])
    return max(groups, key=len) if groups else []


def _inside_cell(shape: ExampleShape, cell: ExampleShape) -> bool:
    x, y = _center(shape)
    return cell.x <= x <= cell.x + cell.cx and cell.y <= y <= cell.y + cell.cy


def _by_the_example(ds: DesignSystem, example: TemplateExample) -> tuple[dict[str, int], int]:
    """Повторы, найденные по самому примеру, — когда компонент шаблона молчит.

    Фигура попадает в повтор по попаданию центра в саму ячейку: ячейки не пересекаются,
    и для сетки это надёжнее арифметики шага — шаг между строками и внутри строки разный.
    """
    cells = _row_in_the_example(ds, example)
    if len(cells) < 2:
        return {}, 0
    mapping = {
        shape.shape_id: index
        for shape in example.shapes
        for index, cell in enumerate(cells)
        if _inside_cell(shape, cell)
    }
    #: Повтор — это место под наш текст, и автор шаблона сам его текстом занял: надписью
    #: внутри карточки либо самой ячейкой-надписью. Сетка без текста — орнамент:
    #: у MWS так набраны 50 иконок 1,3 см, у VK Tech — 15. Записать их в повторы значило бы
    #: обещать вёрстке пятьдесят карточек и предлагать плану набить их фактами.
    filled = {
        mapping[shape.shape_id]
        for shape in example.shapes
        if shape.shape_id in mapping and _is_text(shape)
    }
    if len(filled) < 2:
        return {}, 0
    return mapping, len(cells)


def _zones(ds: DesignSystem, example: TemplateExample, repeats: dict[str, int]) -> list[Zone]:
    out: list[Zone] = []
    for shape in example.shapes:
        if not _is_text(shape):
            continue
        level = _level_of(ds, shape)
        size_pt, size_is_own = _size_of(ds, shape, level)
        out.append(
            Zone(
                zone_id=f"z{shape.xml_id}" if shape.xml_id is not None else shape.shape_id,
                xml_id=shape.xml_id,
                role=level,
                repeat=repeats.get(shape.shape_id),
                capacity_chars=_capacity(shape, size_pt),
                size_pt=size_pt,
                size_is_own=size_is_own,
                # Рамка фигуры примера — та, что уже приведена к слайду с масштабом
                # группы (`ExampleShape`). Каталог её знал и выбрасывал (RG18).
                x=shape.x,
                y=shape.y,
                cx=shape.cx,
                cy=shape.cy,
            )
        )
    return out


def _with_title(zones: list[Zone], example: TemplateExample, ds: DesignSystem) -> list[Zone]:
    """Самая крупная зона вне повторов в верхней трети слайда — заголовок слайда.

    Без этого у примера, где автор набрал заголовок свободной фигурой, заголовка нет
    вовсе: по кеглю он попадает в «крупный абзац», и писать в него будет нечего.
    """
    if any(zone.role is TypeLevel.SLIDE_TITLE for zone in zones):
        return zones
    band = ds.grid.height_emu * TOP_BAND_SHARE
    by_id = {shape.shape_id: shape for shape in example.shapes}
    outside = [
        (zone, shape)
        for zone in zones
        if zone.repeat is None and (shape := _shape_of(zone, by_id, example)) is not None
    ]
    #: Сначала ищем в верхней трети — там заголовок стоит обычно. Не нашли, а зоны вне
    #: повторов есть — заголовком становится самая крупная из них, где бы она ни стояла:
    #: слайд без заголовка вёрстке защищать нечем (writer никогда не удаляет заголовок).
    free = [zone for zone, shape in outside if shape.y + shape.cy // 2 <= band] or [
        zone for zone, _shape in outside
    ]
    if not free:
        return zones
    top = max(free, key=lambda zone: (zone.size_pt or 0, zone.capacity_chars, zone.zone_id))
    return [
        zone.model_copy(update={"role": TypeLevel.SLIDE_TITLE}) if zone is top else zone
        for zone in zones
    ]


def _shape_of(
    zone: Zone, by_id: dict[str, ExampleShape], example: TemplateExample
) -> ExampleShape | None:
    for shape in example.shapes:
        if (f"z{shape.xml_id}" if shape.xml_id is not None else shape.shape_id) == zone.zone_id:
            return shape
    return None


def _has_number(ds: DesignSystem, example: TemplateExample, repeats: dict[str, int]) -> bool:
    """Крупное число в повторе: кегль не ниже заголовка слайда, текст короче предложения."""
    title_pt = next(
        (step.size_pt for step in ds.typography.steps if step.level is TypeLevel.SLIDE_TITLE), None
    )
    if title_pt is None:
        return False
    return any(
        shape.shape_id in repeats
        and shape.size_pt is not None
        and shape.size_pt >= title_pt
        and 0 < shape.text_len < NUMBER_TEXT_LEN
        for shape in example.shapes
    )


def _has_large_text(
    ds: DesignSystem, example: TemplateExample, zones: list[Zone], box: tuple[int, int, int, int]
) -> bool:
    area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
    large = {TypeLevel.BODY, TypeLevel.BODY_LARGE}
    for zone in zones:
        if zone.role not in large or zone.repeat is not None:
            continue
        shape = _shape_of(zone, {}, example)
        if shape is not None and shape.cx * shape.cy >= area * LARGE_ZONE_SHARE:
            return True
    return False


def _looks_structural(zones: list[Zone], repeats: dict[str, int], has_picture: bool) -> bool:
    """Похож ли пример на структурный слайд — не только по макету, но и по себе.

    Классификатор макетов зовёт титулом любой макет без тела контента, а таких у шаблонов
    половина: у VK Tech 16 из 37, и на них стоят 42 примера из 54. Пример с девятью зонами,
    рядом карточек и картинкой — содержательный слайд, какое бы имя ни носил его макет.
    """
    return not repeats and not has_picture and len(zones) <= STRUCTURAL_ZONES


def _kind(
    manifest: TemplateManifest,
    ds: DesignSystem,
    example: TemplateExample,
    zones: list[Zone],
    repeats: dict[str, int],
    has_picture: bool,
    box: tuple[int, int, int, int],
) -> RecipeKind | None:
    """Вид рецепта. Порядок разбора — из спецификации: структурный, показатели,
    карточки, текст с картинкой, текст. Первый подошедший и есть вид."""
    layout = next((lt for lt in manifest.layouts if lt.layout_id == example.layout_id), None)
    if (
        layout is not None
        and layout.kind in STRUCTURAL_KINDS
        and _looks_structural(zones, repeats, has_picture)
    ):
        return STRUCTURAL_KINDS[layout.kind]
    if repeats:
        #: Показатели опознаёт сам парсер — он для того и различает виды компонентов.
        #: Крупное число остаётся вторым признаком: у шаблона, где ряд собран плитками,
        #: вид компонента скажет «плитка», а число на ней — что это всё-таки показатели.
        seen = [c for c in manifest.components if example.slide_index in c.seen_on]
        if any(c.kind is ComponentKind.KPI for c in seen) or _has_number(ds, example, repeats):
            return RecipeKind.METRICS
        return RecipeKind.CARDS
    if has_picture:
        return RecipeKind.TEXT_WITH_PICTURE
    #: «Текст» — и явный случай (одна крупная зона во весь контент), и запасной:
    #: композиция без повторов и без крупной картинки, но с заголовком и текстом под ним,
    #: всё равно композиция. Одинокая зона — это подпись или логотип, а не слайд.
    if _has_large_text(ds, example, zones, box) or len(zones) >= STRUCTURAL_ZONES:
        return RecipeKind.TEXT
    return None


def _recipe(
    manifest: TemplateManifest, ds: DesignSystem, example: TemplateExample
) -> Recipe | None:
    if any(shape.kind in UNSUPPORTED_KINDS for shape in example.shapes):
        return None
    box = _content_box(ds)
    repeats, count = _repeat_map(manifest, ds, example)
    zones = _with_title(_zones(ds, example, repeats), example, ds)
    if not zones:
        return None
    area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
    picture = next(
        (
            shape
            for shape in example.shapes
            if shape.kind is ShapeKind.PICTURE
            and _inside(shape, box)
            and shape.cx * shape.cy >= area * LARGE_ZONE_SHARE
        ),
        None,
    )
    kind = _kind(manifest, ds, example, zones, repeats, picture is not None, box)
    if kind is None:
        return None
    return Recipe(
        recipe_id=f"ex{example.slide_index:03d}",
        example_index=example.slide_index,
        part_name=example.part_name,
        kind=kind,
        zones=zones,
        repeats=count if repeats else 0,
        repeat_xml_ids=_repeat_addresses(example, repeats, count),
        has_picture=picture is not None,
        picture_xml_id=picture.xml_id if picture is not None else None,
        origin=Origin.MEASURED,
    )


def _repeat_addresses(
    example: TemplateExample, repeats: dict[str, int], count: int
) -> list[list[int]]:
    """Адреса фигур по повторам: вёрстка удаляет лишний повтор целиком, вместе с плашкой.

    Без этого из ряда исчезала бы только надпись, а плашка под ней оставалась пустой.
    """
    if not repeats or count <= 0:
        return []
    rows: list[list[int]] = [[] for _ in range(count)]
    for shape in example.shapes:
        index = repeats.get(shape.shape_id)
        if index is not None and shape.xml_id is not None:
            rows[index].append(shape.xml_id)
    return rows


def kind_for_visual(suggested_visual: str | None) -> RecipeKind | None:
    """Вид рецепта по заказу плана. Заказ вида `callout:risk` разбирается до двоеточия."""
    if not suggested_visual:
        return None
    return VISUAL_TO_KIND.get(suggested_visual.split(":", 1)[0])


def recipes(manifest: TemplateManifest, ds: DesignSystem) -> list[Recipe]:
    """Каталог композиций шаблона. Порядок — порядок примеров в файле (G01)."""
    return [
        recipe
        for example in manifest.examples
        if (recipe := _recipe(manifest, ds, example)) is not None
    ]
