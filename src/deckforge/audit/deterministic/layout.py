"""Проверки вёрстки (§5.1). Change (15) `audit-deterministic`.

out_of_bounds, overlap, text_overflow, text_clipped, off_guides, margin_violation,
image_aspect_distorted.

Все семь — чистые функции над `SlideIR` и манифестом: на одном и том же слайде
результат всегда один. Пороги приходят из `configs/audit_checks.yaml` через `ctx.params`.

Блок, у которого рамку определить не удалось, проверки пропускают: отсутствие сведений
о геометрии — не то же самое, что блок в нулевых координатах (см. `audit/geometry.py`).
"""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.findings import make_finding
from deckforge.audit.geometry import (
    FULL_BLEED_SHARE,
    block_bbox,
    block_text,
    carries_text,
    covers,
    layout_of,
    positioned_blocks,
    self_positioned_blocks,
)
from deckforge.audit.recipes import catalogue, zone_of
from deckforge.audit.registry import CheckContext, CheckUnavailable, check
from deckforge.domain.audit import Finding
from deckforge.domain.base import BBox
from deckforge.domain.enums import AutoFix, Severity, TextRole
from deckforge.domain.slide import BulletsBlock, SlideIR, TextBlock
from deckforge.domain.template import ShapeKind
from deckforge.domain.units import emu_to_cm


@check(
    id="layout.out_of_bounds",
    deterministic=True,
    severity=Severity.ERROR,
    title="Элемент вышел за границы слайда",
)
def out_of_bounds(ctx: CheckContext) -> Iterable[Finding]:
    """Элемент вышел за границы слайда."""
    slide_box = ctx.manifest.slide_size.bbox
    for slide in ctx.deck.slides:
        for block, bbox in positioned_blocks(slide, ctx.manifest):
            if slide_box.contains(bbox):
                continue
            yield make_finding(
                check_id="layout.out_of_bounds",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=bbox,
                reason="outside",
                message=(
                    f"Блок {block.block_id} выходит за границы слайда: "
                    f"правый край {emu_to_cm(bbox.right):.1f} см, "
                    f"нижний {emu_to_cm(bbox.bottom):.1f} см при холсте "
                    f"{emu_to_cm(slide_box.cx):.1f}×{emu_to_cm(slide_box.cy):.1f} см"
                ),
            )


@check(
    id="layout.overlap",
    deterministic=True,
    severity=Severity.ERROR,
    title="Два блока наложились друг на друга",
)
def overlap(ctx: CheckContext) -> Iterable[Finding]:
    """Два блока наложились друг на друга."""
    threshold = ctx.param("min_overlap_ratio", 0.05)
    slide_box = ctx.manifest.slide_size.bbox
    for slide in ctx.deck.slides:
        placed = positioned_blocks(slide, ctx.manifest)
        layout = layout_of(slide, ctx.manifest)

        # Фигуры макета, несущие содержание: плашка с текстом, врезанная диаграмма,
        # таблица. Блок, легший поверх такой фигуры, перекрывает чужое содержание —
        # это то же наложение, только второй участник приехал из шаблона, а не из плана.
        # Картинки и декоративные фигуры сюда не входят: ими занимается template.decor_moved.
        occupied = [
            shape
            for shape in (layout.shapes if layout is not None else [])
            if shape.kind in (ShapeKind.TEXT, ShapeKind.CHART, ShapeKind.TABLE)
            and not covers(shape.bbox, slide_box, FULL_BLEED_SHARE)
        ]
        for block, bbox in placed:
            if covers(bbox, slide_box, FULL_BLEED_SHARE):
                continue
            for shape in occupied:
                smaller = min(bbox.area, shape.bbox.area)
                if smaller <= 0:
                    continue
                ratio = bbox.intersection_area(shape.bbox) / smaller
                if ratio < threshold:
                    continue
                yield make_finding(
                    check_id="layout.overlap",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=bbox,
                    reason=f"shape:{shape.shape_id}",
                    message=(
                        f"Блок {block.block_id} лёг поверх фигуры макета "
                        f"{shape.shape_id} на {ratio:.0%} её площади"
                    ),
                    evidence={"shape_id": shape.shape_id, "ratio": f"{ratio:.3f}"},
                )

        for index, (block, bbox) in enumerate(placed):
            for other, other_bbox in placed[index + 1 :]:
                # Подложка во весь слайд лежит под контентом по замыслу, а не по ошибке.
                if covers(bbox, slide_box, FULL_BLEED_SHARE) or covers(
                    other_bbox, slide_box, FULL_BLEED_SHARE
                ):
                    continue
                smaller = min(bbox.area, other_bbox.area)
                if smaller <= 0:
                    continue
                ratio = bbox.intersection_area(other_bbox) / smaller
                if ratio < threshold:
                    continue
                yield make_finding(
                    check_id="layout.overlap",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=bbox,
                    reason=f"overlap:{other.block_id}",
                    message=(
                        f"Блоки {block.block_id} и {other.block_id} перекрываются "
                        f"на {ratio:.0%} площади меньшего"
                    ),
                    evidence={"other_block_id": other.block_id, "ratio": f"{ratio:.3f}"},
                )


@check(
    id="layout.text_overflow",
    deterministic=True,
    severity=Severity.ERROR,
    auto_fix=AutoFix.SHRINK_FONT,
    title="Текст не помещается в свою рамку",
)
def text_overflow(ctx: CheckContext) -> Iterable[Finding]:
    """Текст не помещается в свою рамку.

    Предел — замер вёрстки, если он есть; иначе вместимость зоны рецепта, если блок стоит
    в зоне (RG27): у слайда по рецепту рамку дал автор шаблона, а не макет из плана;
    иначе — вместимость макета.
    """
    recipes = catalogue(ctx)
    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            if not isinstance(block, TextBlock | BulletsBlock):
                continue

            # Если вёрстка уже померила блок (change 12), верим измерению, а не оценке.
            measured = slide.fit_report.get(block.block_id)
            if measured is not None:
                if measured.overflow:
                    yield make_finding(
                        check_id="layout.text_overflow",
                        slide_id=slide.slide_id,
                        block_id=block.block_id,
                        bbox=block_bbox(block, layout),
                        reason="measured",
                        message=(
                            f"Текст блока {block.block_id} не помещается в рамку "
                            f"на кегле {measured.final_size_pt:g} pt"
                        ),
                        evidence={"source": "fit_report"},
                    )
                continue

            zone = zone_of(slide, block, recipes)
            if zone is not None:
                yield from _zone_overflow(slide, block, zone.zone_id, zone.capacity_chars)
                continue

            if layout is None:
                continue
            limit = (
                layout.capacity.max_chars_title
                if block.role is TextRole.TITLE
                else layout.capacity.max_chars_body
            )
            length = len(block_text(block))
            if limit <= 0 or length <= limit:
                continue
            yield make_finding(
                check_id="layout.text_overflow",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=block_bbox(block, layout),
                reason="capacity",
                message=(
                    f"Текст блока {block.block_id}: {length} знаков при вместимости "
                    f"макета {limit}"
                ),
                evidence={"source": "capacity", "chars": str(length), "limit": str(limit)},
            )


def _zone_overflow(
    slide: SlideIR, block: TextBlock | BulletsBlock, zone_id: str, limit: int
) -> Iterable[Finding]:
    """Переполнение по вместимости зоны рецепта. Ноль — посчитать не удалось, не судим."""
    length = len(block_text(block))
    if limit <= 0 or length <= limit:
        return
    yield make_finding(
        check_id="layout.text_overflow",
        slide_id=slide.slide_id,
        block_id=block.block_id,
        reason="zone_capacity",
        message=(
            f"Текст блока {block.block_id}: {length} знаков при вместимости "
            f"зоны {zone_id} {limit}"
        ),
        evidence={
            "source": "zone_capacity",
            "zone_id": zone_id,
            "chars": str(length),
            "limit": str(limit),
        },
    )


@check(
    id="layout.text_clipped",
    deterministic=True,
    severity=Severity.ERROR,
    title="Текст обрезан краем слайда",
)
def text_clipped(ctx: CheckContext) -> Iterable[Finding]:
    """Текст обрезан краем слайда."""
    slide_box = ctx.manifest.slide_size.bbox
    for slide in ctx.deck.slides:
        for block, bbox in positioned_blocks(slide, ctx.manifest):
            if not carries_text(block):
                continue
            # Обрезка — это когда часть блока на слайде, а часть за краем.
            # Блок целиком снаружи ловит `layout.out_of_bounds`.
            if slide_box.contains(bbox) or slide_box.intersection_area(bbox) == 0:
                continue
            yield make_finding(
                check_id="layout.text_clipped",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=bbox,
                reason="clipped",
                message=f"Текст блока {block.block_id} обрезан краем слайда",
            )


@check(
    id="layout.off_guides",
    deterministic=True,
    severity=Severity.WARNING,
    auto_fix=AutoFix.SNAP_TO_GUIDE,
    title="Блоки не выровнены по направляющим макета",
)
def off_guides(ctx: CheckContext) -> Iterable[Finding]:
    """Блоки не выровнены по направляющим макета."""
    grid = ctx.manifest.grid
    tolerance = int(ctx.param("tolerance_emu", 0))
    if tolerance <= 0 or not (grid.guides_x_emu or grid.guides_y_emu):
        # Направляющих у шаблона нет — сравнивать не с чем, и выдумывать их нельзя.
        raise CheckUnavailable("в манифесте нет направляющих: выравнивать не по чему")

    for slide in ctx.deck.slides:
        # Только блоки, положение которых выбрали мы: блок в плейсхолдере стоит там,
        # где его поставил автор шаблона, и промахнуться мимо направляющей не мог.
        for block, bbox in self_positioned_blocks(slide, ctx.manifest):
            for axis, value, guides in (
                ("x", bbox.x, grid.guides_x_emu),
                ("y", bbox.y, grid.guides_y_emu),
            ):
                if not guides:
                    continue
                distance = min(abs(guide - value) for guide in guides)
                # Ноль — блок стоит на направляющей. Больше допуска — стоит намеренно
                # в стороне. Нарушение ровно между: промах руки, а не замысел.
                if 0 < distance <= tolerance:
                    yield make_finding(
                        check_id="layout.off_guides",
                        slide_id=slide.slide_id,
                        block_id=block.block_id,
                        bbox=bbox,
                        reason=f"off:{axis}",
                        message=(
                            f"Блок {block.block_id} не дотянут до направляющей по {axis} "
                            f"на {emu_to_cm(distance):.2f} см"
                        ),
                        evidence={"axis": axis, "distance_emu": str(distance)},
                    )


@check(
    id="layout.margin_violation",
    deterministic=True,
    severity=Severity.WARNING,
    title="Контент заходит в поля у краёв",
)
def margin_violation(ctx: CheckContext) -> Iterable[Finding]:
    """Контент заходит в поля у краёв."""
    content_box = ctx.manifest.content_bbox
    slide_box = ctx.manifest.slide_size.bbox
    for slide in ctx.deck.slides:
        # Плейсхолдер шаблона может заходить в поля — это решение автора шаблона,
        # а поля мы вывели статистикой по его же макетам. Спрашиваем только за своё.
        for block, bbox in self_positioned_blocks(slide, ctx.manifest):
            # Полноэкранная плашка или картинка в край — приём шаблона (см. `covers`).
            if covers(bbox, slide_box, FULL_BLEED_SHARE):
                continue
            if content_box.contains(bbox):
                continue
            yield make_finding(
                check_id="layout.margin_violation",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=bbox,
                reason="margin",
                message=(
                    f"Блок {block.block_id} заходит в поля: контентная область "
                    f"{emu_to_cm(content_box.x):.1f}–{emu_to_cm(content_box.right):.1f} см "
                    f"по горизонтали"
                ),
            )


@check(
    id="layout.image_aspect_distorted",
    deterministic=True,
    severity=Severity.ERROR,
    title="Картинка растянута, пропорции нарушены",
)
def image_aspect_distorted(ctx: CheckContext) -> Iterable[Finding]:
    """Картинка растянута, пропорции нарушены.

    Проверка идёт по готовому файлу, а не по IR, и это вынужденно: в `SlideIR`
    растяжение невыразимо. `ImageFit` знает только `cover` и `contain`, а оба режима
    кадрируют, сохраняя пропорции. Растянуть картинку может лишь рендерер, записав
    рамку с пропорцией, отличной от исходной, — увидеть это можно только в `.pptx`.

    Ловить растяжение надо **до** экспорта в pdf и png: после растеризации любая
    картинка выглядит честной, мыло уже запечено внутрь.

    Сравнивается **видимая часть** исходника, а не весь файл (RG49). Кадрирование
    (`a:srcRect`) — законный способ вписать картинку в чужую пропорцию, и он же
    приезжает из шаблона: у VK Education фигура примера скопирована вместе с авторским
    кадром, видимая часть — 0,3045 ширины на 0,45676 высоты, и её пропорция ровно
    квадратная, как рамка. Проверка, не знающая о кадре, обвиняла нас в растяжении,
    которого нет, — две ошибки из пяти на прогоне `2eb47aa89571`.
    """
    path = ctx.deck_path
    if path is None:
        raise CheckUnavailable("файла колоды ещё нет: растяжение видно только в .pptx")
    max_delta = ctx.param("max_aspect_delta", 0.02)

    try:
        from pptx import Presentation
        from pptx.util import Emu
    except ImportError:  # pragma: no cover — библиотека в зависимостях проекта
        return

    try:
        presentation = Presentation(str(path))
    except Exception:
        return

    slide_ids = [slide.slide_id for slide in ctx.deck.slides]
    for number, pptx_slide in enumerate(presentation.slides):
        slide_id = slide_ids[number] if number < len(slide_ids) else None
        for shape in pptx_slide.shapes:
            image = getattr(shape, "image", None)
            if image is None or not shape.width or not shape.height:
                continue
            native_cx, native_cy = image.size
            if not native_cx or not native_cy:
                continue
            visible_cx, visible_cy = _visible(shape, native_cx, native_cy)
            if not visible_cx or not visible_cy:
                continue
            natural = visible_cx / visible_cy
            drawn = shape.width / shape.height
            delta = abs(drawn - natural) / natural
            if delta <= max_delta:
                continue
            yield make_finding(
                check_id="layout.image_aspect_distorted",
                slide_id=slide_id,
                reason=f"aspect:{shape.shape_id}",
                message=(
                    f"Картинка на слайде {number + 1} растянута: пропорция {drawn:.2f} "
                    f"против исходной {natural:.2f}"
                ),
                bbox=BBox(
                    x=int(Emu(shape.left or 0)),
                    y=int(Emu(shape.top or 0)),
                    cx=int(Emu(shape.width)),
                    cy=int(Emu(shape.height)),
                ),
                evidence={"natural": f"{natural:.3f}", "drawn": f"{drawn:.3f}"},
            )


#: Доли `a:srcRect` записаны в тысячных долях процента: 54601 — это 54,601 %.
#: Сто процентов, записанных ими, — вот столько. Не размер и не EMU: множитель формата.
_SRC_RECT_SCALE = 100 * 1000


def _visible(shape: object, native_cx: int, native_cy: int) -> tuple[float, float]:
    """Размер видимой части исходника с учётом кадрирования фигуры.

    Кадра нет — видно весь файл. Стороны кадра заданы долями, которые **отрезаны**
    с каждого края, поэтому видимая доля — единица минус сумма противоположных.
    """
    from pptx.oxml.ns import qn

    # Кадр ищется без оглядки на родителя: у картинки это `p:blipFill`, у заливки
    # фигуры — `a:blipFill`, и пространство имён у них разное.
    element = getattr(shape, "_element", None)
    rect = element.find(f".//{qn('a:srcRect')}") if element is not None else None
    if rect is None:
        return float(native_cx), float(native_cy)

    def cut(*names: str) -> float:
        return sum(int(rect.get(name) or 0) for name in names) / _SRC_RECT_SCALE

    width = max(0.0, 1.0 - cut("l", "r"))
    height = max(0.0, 1.0 - cut("t", "b"))
    return native_cx * width, native_cy * height
