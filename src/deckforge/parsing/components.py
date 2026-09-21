"""Каталог компонентов шаблона по его примерам. Change `design-system-components` (DS3).

Компонент — это то, что автор шаблона нарисовал сам и повторил: карточка, «картинка
с подписью», показатель, шаг таймлайна. В макетах его нет — там только плейсхолдеры,
а компонент живёт на слайдах-примерах свободными фигурами.

Что считать компонентом, а что совпадением, решает повтор. Три экземпляра и больше,
стоящие в ряд или столбцом с **равным шагом**, случайностью не бывают: так автор
показывает, как в этом шаблоне выглядит перечисление. Одинаковый размер сам по себе
признаком не служит — у VK Education 208 картинок 2 × 4 % слайда, и это маркеры списка,
а не компонент.

Экземпляр собирается из нескольких дорожек. На четвёртом слайде VK WorkSpace столбцом
идут сразу три ряда: картинка 2 × 4 %, подложка 6 × 10 % и текст 38 × 10 %, и шаг у всех
трёх одинаковый — 8 % высоты. Это один компонент «картинка с подписью», а не три разных.

Хранятся только параметры (правило 5): цвет — слотом темы, размеры — долями слайда.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

from deckforge.domain.template import (
    ComponentKind,
    ComponentSpec,
    ExampleShape,
    ShapeKind,
    SlideSize,
    TemplateExample,
)

#: Меньше трёх повторов — совпадение, а не система. Порог из задания DS3.
MIN_REPEATS = 3

#: Экземпляр мельче этой доли площади слайда — украшение (маркер, точка, засечка),
#: а не компонент: рисовать по нему плитку не в чем.
MIN_AREA_SHARE = 0.005

#: Насколько шаг между экземплярами может «гулять», оставаясь равным. Ручная раскладка
#: в PowerPoint никогда не даёт точного совпадения, а выравнивание по сетке — почти.
MAX_STEP_SPREAD = 1.35

#: Допуск, с которым размеры двух фигур считаются одинаковыми, — в долях слайда.
SIZE_TOLERANCE = 0.025

#: Кегль во столько раз крупнее соседнего — это показатель, а не вторая строка подписи.
KPI_SIZE_RATIO = 1.6


@dataclass(frozen=True, slots=True)
class _Track:
    """Дорожка: несколько одинаковых фигур, выстроенных с равным шагом."""

    axis: str
    count: int
    step: int
    shapes: tuple[ExampleShape, ...]


def collect_components(
    examples: Iterable[TemplateExample], slide_size: SlideSize
) -> list[ComponentSpec]:
    """Каталог компонентов шаблона. Примеров нет — каталог пуст, и это не ошибка."""
    found: list[ComponentSpec] = []
    for example in examples:
        found.extend(_of_example(example, slide_size))
    return _merge(found)


def _of_example(example: TemplateExample, size: SlideSize) -> list[ComponentSpec]:
    tracks = _tracks(example.shapes, size)
    out: list[ComponentSpec] = []
    # Дорожки одного слайда с одной осью, числом экземпляров и шагом — части одного
    # компонента: у «картинки с подписью» их три, и порознь они ничего не значат.
    grouped: dict[tuple[str, int, int], list[_Track]] = defaultdict(list)
    for track in tracks:
        along = size.cx_emu if track.axis == "row" else size.cy_emu
        # Шаг округляется долей слайда, а не абсолютной величиной: величина в EMU была бы
        # константой под конкретный размер слайда, а у VK Tech он на треть меньше (C6).
        grouped[(track.axis, track.count, round(track.step / along / SIZE_TOLERANCE))].append(
            track
        )
    for (axis, count, _), parts in grouped.items():
        spec = _spec(parts, axis, count, example.slide_index, size)
        if spec is not None:
            out.append(spec)
    return out


def _tracks(shapes: Sequence[ExampleShape], size: SlideSize) -> list[_Track]:
    buckets: dict[tuple[str, int, int], list[ExampleShape]] = defaultdict(list)
    for shape in shapes:
        key = (
            shape.kind.value,
            round(shape.cx / size.cx_emu / SIZE_TOLERANCE),
            round(shape.cy / size.cy_emu / SIZE_TOLERANCE),
        )
        buckets[key].append(shape)

    out: list[_Track] = []
    for group in buckets.values():
        if len(group) < MIN_REPEATS:
            continue
        track = _as_row(group, size) or _as_column(group, size)
        if track is not None:
            out.append(track)
    return out


def _as_row(group: Sequence[ExampleShape], size: SlideSize) -> _Track | None:
    if len({round(s.y / size.cy_emu / SIZE_TOLERANCE) for s in group}) > 2:
        return None
    ordered = sorted(group, key=lambda s: s.x)
    return _track("row", ordered, [b.x - a.x for a, b in pairwise(ordered)])


def _as_column(group: Sequence[ExampleShape], size: SlideSize) -> _Track | None:
    if len({round(s.x / size.cx_emu / SIZE_TOLERANCE) for s in group}) > 2:
        return None
    ordered = sorted(group, key=lambda s: s.y)
    return _track("column", ordered, [b.y - a.y for a, b in pairwise(ordered)])


def _track(axis: str, ordered: Sequence[ExampleShape], steps: Sequence[int]) -> _Track | None:
    """Дорожка состоялась, если шаг между соседями всюду примерно одинаков."""
    if not steps or min(steps) <= 0 or max(steps) / min(steps) > MAX_STEP_SPREAD:
        return None
    return _Track(axis=axis, count=len(ordered), step=round(median(steps)), shapes=tuple(ordered))


def _spec(
    parts: Sequence[_Track], axis: str, count: int, slide_index: int, size: SlideSize
) -> ComponentSpec | None:
    """Один компонент из дорожек: рамка экземпляра — объемлющая по всем его частям."""
    first = [track.shapes[0] for track in parts]
    left = min(shape.x for shape in first)
    top = min(shape.y for shape in first)
    right = max(shape.x + shape.cx for shape in first)
    bottom = max(shape.y + shape.cy for shape in first)
    width = (right - left) / size.cx_emu
    height = (bottom - top) / size.cy_emu
    if width <= 0 or height <= 0 or width * height < MIN_AREA_SHARE:
        return None

    step = median(track.step for track in parts)
    along = size.cx_emu if axis == "row" else size.cy_emu
    sizes = sorted(
        {shape.size_pt for track in parts for shape in track.shapes if shape.size_pt},
        reverse=True,
    )
    kinds = {shape.kind for shape in first}
    filled = next((shape for shape in first if shape.fill_ref or shape.fill_hex), None)
    return ComponentSpec(
        kind=_kind_of(kinds, sizes),
        repeats=count,
        axis=axis,
        width_share=min(1.0, width),
        height_share=min(1.0, height),
        gap_share=min(1.0, max(0.0, step / along)),
        parts=sorted(kinds, key=lambda kind: kind.value),
        text_sizes_pt=sizes,
        fill_ref=filled.fill_ref if filled else None,
        fill_hex=filled.fill_hex if filled else None,
        seen_on=[slide_index],
    )


def _kind_of(kinds: set[ShapeKind], sizes: Sequence[float]) -> ComponentKind:
    """Вид компонента по составу экземпляра.

    Картинка рядом с текстом — «картинка с подписью»: именно так VK WorkSpace показывает
    перечисление. Два кегля, из которых один заметно крупнее, — показатель: значение
    и подпись под ним. Всё остальное — плитка.
    """
    if ShapeKind.PICTURE in kinds and ShapeKind.TEXT in kinds:
        return ComponentKind.PICTURE_CAPTION
    if len(sizes) >= 2 and sizes[0] >= sizes[1] * KPI_SIZE_RATIO:
        return ComponentKind.KPI
    return ComponentKind.TILE


def _merge(found: Sequence[ComponentSpec]) -> list[ComponentSpec]:
    """Один и тот же компонент с разных слайдов — одна запись, слайды складываются."""
    merged: dict[tuple[ComponentKind, str, int, int], ComponentSpec] = {}
    for spec in found:
        key = (
            spec.kind,
            spec.axis,
            round(spec.width_share / SIZE_TOLERANCE),
            round(spec.height_share / SIZE_TOLERANCE),
        )
        current = merged.get(key)
        if current is None:
            merged[key] = spec
            continue
        merged[key] = current.model_copy(
            update={
                "repeats": max(current.repeats, spec.repeats),
                "seen_on": sorted({*current.seen_on, *spec.seen_on}),
                "fill_ref": current.fill_ref or spec.fill_ref,
                "fill_hex": current.fill_hex or spec.fill_hex,
            }
        )
    return sorted(merged.values(), key=lambda spec: (-len(spec.seen_on), spec.kind.value))
