"""Геометрия составных компонентов вместо SmartArt. Change (21) `smartart-icons`.

Одна раскладка на три потребителя: вписывание текста, запись pptx и html. Пропорции ниже —
политика вёрстки компонента (как доли рамки у диаграммы в html), а не свойства шаблона:
размеры берутся из рамки блока, которую выдал манифест.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import NamedTuple

from deckforge.domain.base import BBox
from deckforge.domain.enums import SmartArtPattern
from deckforge.domain.template import ComponentKind, ComponentSpec
from deckforge.layout.errors import LayoutFitError

SUPPORTED_PATTERNS = frozenset(
    {
        SmartArtPattern.PROCESS,
        SmartArtPattern.TIMELINE,
        SmartArtPattern.CYCLE,
        SmartArtPattern.MATRIX,
    }
)

#: process: промежуток между шагами в долях ширины шага; отступ стрелки — в долях промежутка.
_PROCESS_GAP, _PROCESS_LINK_MARGIN = 0.25, 0.2
#: process: наибольшая высота карточки в её ширинах. Квадрат — предел: карточка выше
#: собственной ширины читается колонкой, а не шагом (прогон 693d464d54fb, слайд s04 —
#: четыре столба 4,4 × 12 см с одной строкой подписи посередине).
_PROCESS_NODE_ASPECT = 1.0
#: matrix: промежуток между плитками в долях плитки; наибольшая высота плитки в её
#: ширинах — квадрат, как у процесса. Плоская плитка (0,6 ширины) не вмещала подпись
#: в две строки даже кеглем тела: прогон 62d577d40a74, подписи ужаты до 9 pt.
_MATRIX_GAP, _MATRIX_NODE_ASPECT = 0.12, 1.0
#: Границы, в которых значение шаблона принимается вместо наших (DS4). Повтор, найденный
#: по одному слайду, иногда даёт шаг меньше самого экземпляра — такой «зазор» сузил бы
#: сетку до нуля.
_MIN_TEMPLATE_GAP, _MAX_TEMPLATE_GAP = 0.02, 0.6
#: Площе квадрата шаблон плитку сделать вправе, выше — нет: предел `_MATRIX_NODE_ASPECT`
#: выведен из живого прогона (693d464d54fb), и карточка выше своей ширины читается
#: колонкой, а не плиткой. У VK Education «плитка» 7 × 13 % слайда — это узкий столбец
#: текста, найденный по повтору, и следовать ему значит вернуть тот самый дефект.
_MIN_TEMPLATE_ASPECT, _MAX_TEMPLATE_ASPECT = 0.3, _MATRIX_NODE_ASPECT
#: timeline: диаметр маркера в долях колонки (или высоты рамки, если она ниже).
_TIMELINE_MARKER = 0.2
#: cycle: наибольшая ширина узла в высотах; зазор между узлами в высотах узла; отступ
#: стрелки от узла в долях зазора; шагов деления пополам (точность — 2⁻³⁰ высоты рамки).
_CYCLE_NODE_ASPECT, _CYCLE_GAP, _CYCLE_LINK_MARGIN = 2.5, 0.35, 0.2
_CYCLE_SEARCH_STEPS = 30
#: Радиус скругления `roundRect` по умолчанию — `adj` 16667/100000 от короткой стороны; поле
#: текста отступает на радиус × (1 − 1/√2). Константы формата (presetShapeDefinitions).
ROUND_RECT_RADIUS = 0.16667
_ROUND_RECT_TEXT_INSET = ROUND_RECT_RADIUS * (1 - 1 / math.sqrt(2))


class Link(NamedTuple):
    """Отрезок коннектора в EMU."""

    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class Diagram:
    #: Закрашенные фигуры: шаги процесса, узлы цикла, маркеры шкалы времени.
    nodes: tuple[BBox, ...]
    #: Где стоит текст элемента: внутри узла или под маркером.
    labels: tuple[BBox, ...]
    links: tuple[Link, ...]
    #: Стрелка на конце коннектора: у процесса и цикла есть направление, у оси времени — нет.
    arrows: bool
    #: Узел — эллипс (маркер шкалы времени), а не скруглённый прямоугольник.
    round_nodes: bool
    #: Текст пишется в сам узел, и `labels` — поле текста его фигуры; иначе текст — отдельная
    #: надпись в `labels` (шкала времени).
    text_inside: bool


def diagram_geometry(
    pattern: SmartArtPattern,
    count: int,
    box: BBox,
    component: ComponentSpec | None = None,
) -> Diagram:
    """Геометрия составного компонента.

    `component` — плитка, которую рисует сам шаблон (DS3). Когда она есть, пропорции
    и зазор берутся у неё: плитки получаются в пропорциях автора шаблона, а не в наших
    (DS4). Нет компонента — раскладка прежняя.
    """
    if count < 1:
        raise LayoutFitError("в составном компоненте нет элементов")
    if pattern is SmartArtPattern.PROCESS:
        return _process(count, box)
    if pattern is SmartArtPattern.TIMELINE:
        return _timeline(count, box)
    if pattern is SmartArtPattern.CYCLE:
        return _cycle(count, box)
    if pattern is SmartArtPattern.MATRIX:
        return _matrix(count, box, *_matrix_shape(component))
    raise LayoutFitError(f"паттерн {pattern.value} не поддерживается составными компонентами")


def _process(count: int, box: BBox) -> Diagram:
    width = box.cx / (count + (count - 1) * _PROCESS_GAP)
    gap = width * _PROCESS_GAP
    # Карточка не выше своей ширины, а ряд стоит по середине рамки: решатель отдаёт
    # блоку всю свободную площадь слайда, и растянутая на неё карточка — не шаг, а столб.
    height = min(box.cy, max(1, int(width * _PROCESS_NODE_ASPECT)))
    top = box.y + (box.cy - height) // 2
    nodes = tuple(
        BBox(x=box.x + int(i * (width + gap)), y=top, cx=max(1, int(width)), cy=height)
        for i in range(count)
    )
    labels = tuple(_inset(node, round(min(node.cx, node.cy) * _ROUND_RECT_TEXT_INSET))
                   for node in nodes)
    margin = round(gap * _PROCESS_LINK_MARGIN)
    middle = box.y + box.cy // 2
    links = tuple(
        Link(a.right + margin, middle, b.x - margin, middle)
        for a, b in pairwise(nodes)
    )
    return Diagram(nodes=nodes, labels=labels, links=links, arrows=True, round_nodes=False,
                   text_inside=True)


def _matrix_columns(count: int, box: BBox) -> int:
    """Столбцов в сетке — столько, чтобы у плитки была больше короткая сторона.

    Число столбцов по одному счёту пунктов не годится: рамку схеме отдаёт решатель,
    и она бывает и широкой, и узкой. Прогон 62d577d40a74: пять плиток по три в ряд
    в рамке шириной 9 см — плитки по 2,7 см, «Компьютерное» не встаёт в строку,
    и подписи ужаты до 9 pt. Две колонки в той же рамке дают плитки по 4 см.
    """
    def short_side(columns: int) -> float:
        rows = -(-count // columns)
        width = box.cx / (columns + (columns - 1) * _MATRIX_GAP)
        height = (box.cy - (rows - 1) * width * _MATRIX_GAP) / rows
        return min(width, height, width * _MATRIX_NODE_ASPECT)

    return max(range(1, count + 1), key=lambda columns: (short_side(columns), -columns))


def _matrix_shape(component: ComponentSpec | None) -> tuple[float, float]:
    """(зазор в долях плитки, наибольшая высота в ширинах) — от шаблона или наши.

    Шаблон говорит о плитке двумя числами: какой она формы и как далеко стоит от
    соседней. Оба берутся из повтора, который автор нарисовал сам: зазор — это шаг
    между экземплярами минус сам экземпляр, а форма — высота экземпляра в его ширинах.

    Нелепые значения отбрасываются: у повтора, найденного по одному слайду, шаг бывает
    меньше самой плитки (экземпляры перекрываются), и такой «зазор» сузил бы сетку
    до нуля. Границы взяты с запасом вокруг наших прежних 0,12.
    """
    if component is None or component.kind is not ComponentKind.TILE:
        return _MATRIX_GAP, _MATRIX_NODE_ASPECT
    along = component.width_share if component.axis == "row" else component.height_share
    gap = (component.gap_share - along) / along if along > 0 else 0.0
    # `ComponentSpec.aspect` — ширина к высоте, а раскладке нужна высота в ширинах:
    # величины обратные, и перепутать их значит сделать плитку вдвое выше вместо вдвое площе.
    aspect = 1 / component.aspect if component.aspect > 0 else _MATRIX_NODE_ASPECT
    return (
        gap if _MIN_TEMPLATE_GAP <= gap <= _MAX_TEMPLATE_GAP else _MATRIX_GAP,
        aspect if _MIN_TEMPLATE_ASPECT <= aspect <= _MAX_TEMPLATE_ASPECT
        else _MATRIX_NODE_ASPECT,
    )


def _matrix(
    count: int,
    box: BBox,
    gap_share: float = _MATRIX_GAP,
    node_aspect: float = _MATRIX_NODE_ASPECT,
) -> Diagram:
    """Однородные пункты плитками: без стрелок, потому что порядка у них нет.

    Сколько плиток в ряд, решает форма рамки (`_matrix_columns`), а не только их число.

    Перечисление — «инференс, шаблоны, контент, CLI» — это не шаги: стрелки процесса
    соврали бы о последовательности, которой нет. Сетка стоит по середине рамки,
    неполный последний ряд — по центру, чтобы сетка не заваливалась влево.
    """
    columns = _matrix_columns(count, box)
    rows = -(-count // columns)
    width = box.cx / (columns + (columns - 1) * gap_share)
    gap_x = width * gap_share
    cell = (box.cy - (rows - 1) * gap_x) / rows
    height = max(1, int(min(cell, width * node_aspect)))
    grid_height = rows * height + (rows - 1) * gap_x
    top = box.y + (box.cy - grid_height) / 2

    nodes: list[BBox] = []
    for index in range(count):
        row, column = divmod(index, columns)
        in_row = min(columns, count - row * columns)
        row_width = in_row * width + (in_row - 1) * gap_x
        left = box.x + (box.cx - row_width) / 2
        nodes.append(BBox(
            x=int(left + column * (width + gap_x)),
            y=int(top + row * (height + gap_x)),
            cx=max(1, int(width)),
            cy=height,
        ))
    labels = tuple(_inset(node, round(min(node.cx, node.cy) * _ROUND_RECT_TEXT_INSET))
                   for node in nodes)
    return Diagram(nodes=tuple(nodes), labels=labels, links=(), arrows=False,
                   round_nodes=False, text_inside=True)


def _timeline(count: int, box: BBox) -> Diagram:
    column = box.cx // count
    marker = max(1, round(min(column, box.cy) * _TIMELINE_MARKER))
    label_y = box.y + marker + marker // 2
    nodes = tuple(
        BBox(x=box.x + i * column + (column - marker) // 2, y=box.y, cx=marker, cy=marker)
        for i in range(count)
    )
    labels = tuple(
        BBox(x=box.x + i * column, y=label_y, cx=column, cy=max(1, box.bottom - label_y))
        for i in range(count)
    )
    axis = Link(box.x, box.y + marker // 2, box.right, box.y + marker // 2)
    return Diagram(nodes=nodes, labels=labels, links=(axis,), arrows=False, round_nodes=True,
                   text_inside=False)


def _cycle(count: int, box: BBox) -> Diagram:
    """Узлы на эллипсе, вписанном в рамку, от верхней точки по часовой стрелке; стрелка —
    к следующему узлу.

    Узел — скруглённый прямоугольник с пропорциями рамки (не шире `_CYCLE_NODE_ASPECT`):
    круги по короткой стороне оставляли под текст квадратик. Высота узла — наибольшая, при
    которой любые два узла разнесены хотя бы на `_CYCLE_GAP` высоты по одной из осей:
    в этом зазоре и стоит стрелка. Ищется делением пополам — формулы для эллипса нет.
    """
    aspect = min(max(box.cx / box.cy, 1.0), _CYCLE_NODE_ASPECT)

    def centres(height: float) -> list[tuple[float, float]]:
        width = height * aspect
        rx, ry = (box.cx - width) / 2, (box.cy - height) / 2
        angles = [-math.pi / 2 + 2 * math.pi * i / count for i in range(count)]
        return [(box.x + box.cx / 2 + rx * math.cos(a), box.y + box.cy / 2 + ry * math.sin(a))
                for a in angles]

    def separated(height: float) -> bool:
        """Узлы разнесены на зазор, и стрелка между соседями не идёт сквозь чужой узел:
        в вытянутой полосе нижняя стрелка цикла из трёх задевала верхний узел."""
        width, gap = height * aspect, height * _CYCLE_GAP
        points = centres(height)
        if not all(
            abs(ax - bx) >= width + gap or abs(ay - by) >= height + gap
            for i, (ax, ay) in enumerate(points)
            for bx, by in points[i + 1:]
        ):
            return False
        return not any(
            _crosses(points[i], points[(i + 1) % count], points[j], width, height)
            for i in range(count)
            for j in range(count)
            if count > 2 and j not in (i, (i + 1) % count)
        )

    low, high = 0.0, min(box.cy, box.cx / aspect)
    for _ in range(_CYCLE_SEARCH_STEPS):
        middle = (low + high) / 2
        low, high = (middle, high) if separated(middle) else (low, middle)
    height = max(1, int(low))
    width = max(1, int(low * aspect))
    points = centres(low)
    nodes = tuple(_box_at(x, y, width, height, box) for x, y in points)
    labels = tuple(
        _inset(node, round(min(node.cx, node.cy) * _ROUND_RECT_TEXT_INSET)) for node in nodes
    )

    links: list[Link] = []
    margin = low * _CYCLE_GAP * _CYCLE_LINK_MARGIN
    for i in range(count):
        (ax, ay), (bx, by) = points[i], points[(i + 1) % count]
        length = math.hypot(bx - ax, by - ay)
        if length == 0:
            continue
        ux, uy = (bx - ax) / length, (by - ay) / length
        if count == 2:
            # Туда и обратно между двумя узлами — две стрелки рядом, а не одна поверх другой.
            shift = width / 4
            ax, ay, bx, by = ax - uy * shift, ay + ux * shift, bx - uy * shift, by + ux * shift
        # Сколько пройти от центра до края прямоугольника вдоль направления стрелки.
        edge = min(width / 2 / abs(ux) if ux else math.inf,
                   height / 2 / abs(uy) if uy else math.inf)
        offset = edge + margin
        if length <= 2 * offset:
            continue
        links.append(Link(round(ax + ux * offset), round(ay + uy * offset),
                          round(bx - ux * offset), round(by - uy * offset)))
    return Diagram(nodes=nodes, labels=labels, links=tuple(links), arrows=True,
                   round_nodes=False, text_inside=True)


def _crosses(
    a: tuple[float, float], b: tuple[float, float], centre: tuple[float, float],
    width: float, height: float,
) -> bool:
    """Пересекает ли отрезок `a`–`b` прямоугольник с центром `centre` (Лианг — Барски)."""
    left, top = centre[0] - width / 2, centre[1] - height / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    low, high = 0.0, 1.0
    for p, q in ((-dx, a[0] - left), (dx, left + width - a[0]),
                 (-dy, a[1] - top), (dy, top + height - a[1])):
        if p == 0:
            if q <= 0:
                return False
        elif p < 0:
            low = max(low, q / p)
        else:
            high = min(high, q / p)
    return low < high


def _inset(box: BBox, by: int) -> BBox:
    return BBox(x=box.x + by, y=box.y + by, cx=max(1, box.cx - 2 * by),
                cy=max(1, box.cy - 2 * by))


def _box_at(centre_x: float, centre_y: float, width: int, height: int, box: BBox) -> BBox:
    x = min(max(round(centre_x - width / 2), box.x), box.right - width)
    y = min(max(round(centre_y - height / 2), box.y), box.bottom - height)
    return BBox(x=x, y=y, cx=width, cy=height)
