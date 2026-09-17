"""Сетка, поля и направляющие. Change (4) `theme-extraction`.

Направляющие есть в XML далеко не всегда: из трёх шаблонов организаторов они нашлись
в одном. Поэтому основной путь — **вывод** направляющих кластеризацией координат
плейсхолдеров, а поле `guides_source` честно говорит, откуда они взялись.
"""

from __future__ import annotations

from itertools import pairwise

from lxml import etree

from deckforge.domain.enums import LayoutKind
from deckforge.domain.template import Grid, LayoutSpec, Margins, PlaceholderSpec, SlideSize
from deckforge.domain.units import EMU_PER_GUIDE_UNIT

P = "http://schemas.openxmlformats.org/presentationml/2006/main"

#: Доля ширины слайда, в пределах которой две координаты считаются одной направляющей.
_CLUSTER_TOLERANCE = 0.01

#: Сколько макетов должны согласиться, чтобы координата стала направляющей, а не случайностью.
_MIN_SUPPORT = 2

#: Доля слайда, начиная с которой плейсхолдер считается сделанным «в край».
_FULL_BLEED_SHARE = 0.95

#: Виды макетов, чья геометрия годится в основание сетки: у них плейсхолдер
#: действительно несёт тело контента, а не декоративный заголовок обложки/раздела.
_BODY_KINDS = frozenset({
    LayoutKind.BULLETS, LayoutKind.TWO_COLUMN, LayoutKind.CHART,
    LayoutKind.TABLE, LayoutKind.KPI, LayoutKind.CUSTOM,
})

#: Запасные поля, когда в шаблоне вообще нет макета с телом контента (§ниже).
#: Ориентир — обычные поля презентации, не подогнанные под конкретный шаблон.
_FALLBACK_MARGIN_SHARE_X = 0.07
_FALLBACK_MARGIN_SHARE_Y = 0.10


def extract_guides(view_props_xml: bytes | None) -> tuple[list[int], list[int]] | None:
    """Направляющие из `ppt/viewProps.xml`, если автор шаблона их расставил.

    `orient="horz"` — горизонтальная линия, то есть координата по **оси Y**.
    """
    if not view_props_xml:
        return None

    root = etree.fromstring(view_props_xml)
    xs: list[int] = []
    ys: list[int] = []
    for guide in root.iter(f"{{{P}}}guide"):
        raw = guide.get("pos")
        if not raw:
            continue
        # pos задаётся в 1/8 точки.
        position = round(int(raw) * EMU_PER_GUIDE_UNIT)
        (ys if guide.get("orient") == "horz" else xs).append(position)

    if not xs and not ys:
        return None
    return sorted(set(xs)), sorted(set(ys))


def cluster_positions(values: list[int], tolerance: int, min_support: int) -> list[int]:
    """Одномерная кластеризация координат: соседние в пределах допуска — одна направляющая.

    Возвращает центры кластеров, набравших поддержку. Порог отсекает координаты,
    встретившиеся в одном-единственном макете: это личная особенность макета, а не сетка.
    """
    if not values:
        return []

    clusters: list[list[int]] = [[values[0]]]
    for value in sorted(values)[1:]:
        if value - clusters[-1][-1] <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])

    return [
        round(sum(cluster) / len(cluster))
        for cluster in clusters
        if len(cluster) >= min_support
    ]


def infer_margins(layouts: list[LayoutSpec], slide_size: SlideSize) -> Margins:
    """Поля — минимальные отступы, которые шаблон выдерживает в **текстовых** макетах.

    Берётся минимум, а не среднее: поле, в которое заходит текст хоть одного макета,
    полем не является, и аудит `layout.margin_violation` начал бы ругаться на сам шаблон.

    Из расчёта исключены плейсхолдеры «в край»: макет с полноэкранной картинкой или
    цветной плашкой — это осознанный приём шаблона, а не отмена полей для текста.
    Без этого исключения поля почти любого реального шаблона схлопываются в ноль.

    Если в шаблоне нет ни одного макета с телом контента (`_BODY_KINDS`) — только
    обложки и разделители, — эта же логика ломается иначе: единственный источник
    геометрии тогда декоративный, а декоративные макеты по двум осям выбивают
    отступы в разные стороны. На шаблоне из одних title-only макетов вертикально
    центрированная обложка утягивает нижнее поле почти на треть высоты слайда, а
    исключение этого макета из выборки делает поле уже противоположно неверным —
    вместо чрезмерно щедрого получается втрое теснее, чем нужно (проверено на VK
    WorkSpace: 15 из 15 макетов — обложки/заголовки/разделители без тела). Разные
    оси при этом ломаются в противоположные стороны, поэтому подрезка одного
    выброса не работает: это не шум одной оси, а отсутствие сигнала как такового.
    В этом случае — и только в нём — берутся обычные поля презентации, не
    подогнанные под конкретный шаблон, а не геометрия декоративных макетов.
    """
    if layouts and not any(layout.kind in _BODY_KINDS for layout in layouts):
        return Margins(
            left=round(slide_size.cx_emu * _FALLBACK_MARGIN_SHARE_X),
            right=round(slide_size.cx_emu * _FALLBACK_MARGIN_SHARE_X),
            top=round(slide_size.cy_emu * _FALLBACK_MARGIN_SHARE_Y),
            bottom=round(slide_size.cy_emu * _FALLBACK_MARGIN_SHARE_Y),
        )

    boxes = [
        ph.bbox
        for layout in layouts
        for ph in layout.placeholders
        if ph.role is not None and not _is_full_bleed(ph, slide_size)
    ]
    if not boxes:
        boxes = [ph.bbox for layout in layouts for ph in layout.placeholders]
    if not boxes:
        return Margins(left=0, right=0, top=0, bottom=0)

    return Margins(
        left=max(0, min(b.x for b in boxes)),
        top=max(0, min(b.y for b in boxes)),
        right=max(0, slide_size.cx_emu - max(b.right for b in boxes)),
        bottom=max(0, slide_size.cy_emu - max(b.bottom for b in boxes)),
    )


def _is_full_bleed(ph: PlaceholderSpec, slide_size: SlideSize) -> bool:
    return (
        ph.cx >= slide_size.cx_emu * _FULL_BLEED_SHARE
        or ph.cy >= slide_size.cy_emu * _FULL_BLEED_SHARE
    )


def infer_grid(
    layouts: list[LayoutSpec],
    slide_size: SlideSize,
    view_props_xml: bytes | None = None,
) -> Grid:
    """Сетка шаблона: поля, направляющие, число колонок."""
    margins = infer_margins(layouts, slide_size)

    explicit = extract_guides(view_props_xml)
    if explicit is not None:
        guides_x, guides_y = explicit
        source = "xml"
    else:
        tolerance = int(slide_size.cx_emu * _CLUSTER_TOLERANCE)
        edges_x = [
            v
            for layout in layouts
            for ph in layout.placeholders
            for v in (ph.x, ph.bbox.right)
        ]
        edges_y = [
            v
            for layout in layouts
            for ph in layout.placeholders
            for v in (ph.y, ph.bbox.bottom)
        ]
        guides_x = cluster_positions(edges_x, tolerance, _MIN_SUPPORT)
        guides_y = cluster_positions(edges_y, tolerance, _MIN_SUPPORT)
        source = "inferred"

    content_width = max(1, slide_size.cx_emu - margins.left - margins.right)
    columns = _infer_columns(guides_x, margins.left, content_width)
    gutter = _infer_gutter(guides_x)

    return Grid(
        margins_emu=margins,
        guides_x_emu=guides_x,
        guides_y_emu=guides_y,
        columns=columns,
        gutter_emu=gutter,
        guides_source=source,
    )


def _infer_columns(guides_x: list[int], left: int, content_width: int) -> int:
    """Число колонок — то из 12/6/4/3/2, на которое направляющие ложатся точнее.

    Это перебор кандидатов, а не знание конкретного шаблона: если ни один не подошёл,
    остаётся 12 — нейтральная база, от которой composition всё равно считает доли.
    """
    if not guides_x or content_width <= 0:
        return 12

    best_columns, best_error = 12, float("inf")
    for candidate in (12, 6, 4, 3, 2):
        step = content_width / candidate
        error = sum(
            abs((guide - left) - round((guide - left) / step) * step) for guide in guides_x
        ) / len(guides_x)
        if error < best_error:
            best_columns, best_error = candidate, error

    # Промах больше четверти колонки означает, что сетки в этом шаблоне просто нет.
    return best_columns if best_error < content_width / best_columns / 4 else 12


def _infer_gutter(guides_x: list[int]) -> int:
    """Межколоночник — наименьший ненулевой зазор между соседними направляющими."""
    gaps = [b - a for a, b in pairwise(guides_x) if b > a]
    return min(gaps) if gaps else 0
