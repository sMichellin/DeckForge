"""Constraint-решатель (kiwisolver) для блоков без плейсхолдера. Change (12).

Блоки с координатами остаются на месте. Свободные делят поровну наибольший свободный
прямоугольник области контента: колонками, если он шире своей высоты, иначе строками.
Промежуток — шаг шкалы отступов дизайн-системы, который передаёт композиция
(`DesignRules.block_gap_emu`, DG3); не передан — `grid.gutter_emu` шаблона, как было.
Своих чисел геометрии здесь нет.

Перекрытие закреплённых блоков между собой здесь не проверяется: координаты задал
композитор, а перекрытия ловит аудит (`layout.*`).
"""

from __future__ import annotations

from itertools import combinations

from kiwisolver import Solver, UnsatisfiableConstraint, Variable

from deckforge.domain.base import BBox
from deckforge.domain.template import TemplateManifest
from deckforge.layout.errors import LayoutFitError


def _free_rect(content: BBox, fixed: list[BBox]) -> BBox | None:
    """Наибольший прямоугольник области контента, не задевающий закреплённые блоки.

    Стороны такого прямоугольника всегда лежат на краях области или блоков, поэтому
    достаточно перебрать пары краёв. Блоков на слайде единицы — перебор дешёвый.
    При равной площади выигрывает найденный раньше: левее и выше.
    """
    if not fixed:
        return content
    xs = sorted({content.x, content.right, *(e for b in fixed for e in (b.x, b.right))})
    ys = sorted({content.y, content.bottom, *(e for b in fixed for e in (b.y, b.bottom))})
    best: BBox | None = None
    for x0, x1 in combinations(xs, 2):
        for y0, y1 in combinations(ys, 2):
            area = (x1 - x0) * (y1 - y0)
            if best is not None and area <= best.area:
                continue
            candidate = BBox(x=x0, y=y0, cx=x1 - x0, cy=y1 - y0)
            if not any(candidate.intersection_area(b) for b in fixed):
                best = candidate
    return best


def _split(band: BBox, count: int, gutter: int) -> list[BBox]:
    horizontal = band.cx >= band.cy
    start, length = (band.x, band.cx) if horizontal else (band.y, band.cy)
    if count + (count - 1) * gutter > length:
        raise LayoutFitError(f"в {band} не помещается {count} блоков с промежутком {gutter}")

    solver = Solver()
    offsets = [Variable(f"offset{i}") for i in range(count)]
    sizes = [Variable(f"size{i}") for i in range(count)]
    try:
        solver.addConstraint(offsets[0] == start)
        solver.addConstraint(offsets[-1] + sizes[-1] == start + length)
        for i in range(count):
            solver.addConstraint(sizes[i] >= 1)
            if i:
                solver.addConstraint(offsets[i] == offsets[i - 1] + sizes[i - 1] + gutter)
                solver.addConstraint(sizes[i] == sizes[0])
    except UnsatisfiableConstraint as exc:
        raise LayoutFitError(f"в {band} не помещается {count} блоков") from exc
    solver.updateVariables()

    out = []
    for offset, size in zip(offsets, sizes, strict=True):
        lo, hi = round(offset.value()), round(offset.value() + size.value())
        if hi <= lo:
            raise LayoutFitError(f"в {band} не помещается {count} блоков")
        if horizontal:
            out.append(BBox(x=lo, y=band.y, cx=hi - lo, cy=band.cy))
        else:
            out.append(BBox(x=band.x, y=lo, cx=band.cx, cy=hi - lo))
    return out


def solve_positions(
    blocks: list[tuple[str, BBox | None]],
    manifest: TemplateManifest,
    *,
    gap_emu: int | None = None,
) -> dict[str, BBox]:
    """Раскладывает блоки по сетке, не выходя за поля и не перекрываясь.

    `gap_emu` — промежуток между свободными блоками. Решает, чему он кратен, дизайн-система
    (`grid.spacing`), а не решатель: он только делит полосу."""
    content = manifest.content_bbox
    fixed = {block_id: box for block_id, box in blocks if box is not None}
    free = [block_id for block_id, box in blocks if box is None]

    for block_id, box in fixed.items():
        if not content.contains(box):
            raise LayoutFitError(f"блок {block_id} выходит за поля шаблона: {box}")
    if not free:
        return dict(fixed)

    band = _free_rect(content, list(fixed.values()))
    if band is None:
        raise LayoutFitError("закреплённые блоки заняли всю область контента")
    gap = manifest.grid.gutter_emu if gap_emu is None else gap_emu
    placed = _split(band, len(free), gap)
    return {**fixed, **dict(zip(free, placed, strict=True))}
