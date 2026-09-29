"""Проверки вёрстки (§5.1). Change (15) `audit-deterministic`.

out_of_bounds, overlap, text_overflow, text_clipped, off_guides, margin_violation,
image_aspect_distorted, object_overflow.

Все семь — чистые функции над `SlideIR` и манифестом: на одном и том же слайде
результат всегда один. Пороги приходят из `configs/audit_checks.yaml` через `ctx.params`.

Блок, у которого рамку определить не удалось, проверки пропускают: отсутствие сведений
о геометрии — не то же самое, что блок в нулевых координатах (см. `audit/geometry.py`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

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
from deckforge.domain.slide import (
    Block,
    BulletsBlock,
    ChartBlock,
    SlideIR,
    SmartArtBlock,
    TableBlock,
    TextBlock,
)
from deckforge.domain.template import ShapeKind
from deckforge.domain.units import TEXT_FRAME_INSET_X_EMU, TEXT_FRAME_INSET_Y_EMU, emu_to_cm


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
    """Два блока наложились друг на друга.

    Заголовок судится строже (`_crowds_the_title`, план Б, круг 2): выноска, упёршаяся
    в него текстом, и блок в полосе над ним видны сразу, какую бы долю площади ни заняли.
    """
    threshold = ctx.param("min_overlap_ratio", 0.05)
    slide_box = ctx.manifest.slide_size.bbox
    for slide in ctx.deck.slides:
        placed = positioned_blocks(slide, ctx.manifest)
        layout = layout_of(slide, ctx.manifest)
        yield from _crowds_the_title(slide, placed, slide_box, threshold)

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


def _occupied(slide: SlideIR, block: Block, bbox: BBox) -> BBox:
    """Место блока: рамка, а если текст не влез — до замеренной высоты текста вниз.

    Не влезший текст выходит за рамку (`fit_report.required_cy_emu`), и рядом стоящий
    заголовок он задевает текстом, а не рамкой — рамки при этом лишь касаются.
    """
    measured = slide.fit_report.get(block.block_id)
    required = measured.required_cy_emu if measured is not None else None
    if not required or required <= bbox.cy:
        return bbox
    return BBox(x=bbox.x, y=bbox.y, cx=bbox.cx, cy=required)


def _crowds_the_title(
    slide: SlideIR, placed: list[tuple[Block, BBox]], slide_box: BBox, threshold: float
) -> Iterable[Finding]:
    """Блок, который мы поставили, задевает заголовок или стоит в полосе над ним.

    Education 29.09 s02, s08: решатель положил выноску и схему над заголовком, их текст
    не влез и упёрся в заголовок. Рамки только касались, а от площади меньшего блока
    пересечение — четыре процента, ниже порога, и проверка молчала. Заголовок —
    не рядовой сосед: касание его видно сразу, поэтому порога площади для него нет.

    Судятся только блоки со своими координатами (`block.bbox`): положение плейсхолдера
    выбрал автор шаблона. Полоса над заголовком — только у заголовка в верхней половине
    слайда: над заголовком внизу слайда содержанию место есть.
    """
    titles = [
        (block, bbox) for block, bbox in placed if getattr(block, "role", None) is TextRole.TITLE
    ]
    for block, bbox in placed:
        if block.bbox is None or getattr(block, "role", None) is TextRole.TITLE:
            continue
        taken = _occupied(slide, block, bbox)
        for title, title_box in titles:
            smaller = min(bbox.area, title_box.area)
            if smaller > 0 and bbox.intersection_area(title_box) / smaller >= threshold:
                continue  # это наложение рамок, его назовёт общая часть проверки
            across = min(taken.right, title_box.right) - max(taken.x, title_box.x) > 0
            touches = taken.intersection_area(title_box) > 0
            above = across and taken.bottom <= title_box.y and title_box.y < slide_box.cy // 2
            if not touches and not above:
                continue
            yield make_finding(
                check_id="layout.overlap",
                slide_id=slide.slide_id,
                block_id=block.block_id,
                bbox=taken,
                reason=f"title:{title.block_id}",
                message=(
                    f"Блок {block.block_id} ({block.type}) "
                    + ("задевает заголовок" if touches else "стоит в полосе над заголовком")
                    + f" {title.block_id}"
                ),
                evidence={
                    "title_block_id": title.block_id,
                    "kind": "touches" if touches else "above",
                },
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


# --- переполненная таблица или схема (план Б, после 5б; change `the-overflowing-table-is-found`)


def _plain(text: str) -> str:
    """Текст для сверки подписи: неразрывные пробелы (Т4) — обычные, края срезаны."""
    return " ".join(text.replace("\u00a0", " ").split())


def _frames_on(page: Any) -> tuple[list[tuple[int, int, int, int]], list[set[str]]]:
    """Таблицы страницы (x, y, cx, cy) и тексты подписей каждой группы фигур."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    tables: list[tuple[int, int, int, int]] = []
    groups: list[set[str]] = []
    for shape in page.shapes:
        if getattr(shape, "has_table", False):
            tables.append((int(shape.left or 0), int(shape.top or 0),
                           int(shape.width or 0), int(shape.height or 0)))
        elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            groups.append({
                _plain(child.text_frame.text)
                for child in shape.shapes
                if getattr(child, "has_text_frame", False) and child.text_frame.text.strip()
            })
    return tables, groups


@check(
    id="layout.object_overflow",
    deterministic=True,
    severity=Severity.ERROR,
    title="Таблица или схема записана с переполнением",
)
def object_overflow(ctx: CheckContext) -> Iterable[Finding]:
    """Таблица или схема записана с переполнением (план Б, после 5б).

    На пути `by_example` слайд без примера больше не сплющивает не влезший блок: таблица
    и схема пишутся своим видом «как есть», а переполнение названо только заметкой
    в `degradations`. `layout.text_overflow` смотрит лишь текст и списки — вылет таблицы
    или схемы аудиту не был виден, и строки 5 и 9 плана Б сдвигались бы за счёт него.

    Меряется **записанный файл**, а не решение писателя:

    * таблица (и диаграмма, которую писатель заменил таблицей) — рамка таблицы на месте блока
      выше места блока (`bbox` в IR) больше `height_tolerance`: писатель ставит строкам
      измеренные высоты, и рамка — их сумма;
    * схема — `fit_report` называет переполнение, и в файле она нарисована группой с подписями
      пунктов, а не заменена списком (список — забота `layout.text_overflow`).

    Без файла — пропуск: по одному IR не видно, каким видом блок записан.
    """
    path = ctx.deck_path
    if path is None:
        raise CheckUnavailable("файла колоды ещё нет: каким видом записан блок, видно в .pptx")
    tolerance = ctx.param("height_tolerance", 0.02)
    # Угол рамки таблицы и угол места блока совпадают по построению; допуск — доля ширины
    # слайда, а не EMU: размер слайда у шаблонов разный (правило 2).
    near = ctx.param("position_share", 0.005) * ctx.manifest.slide_size.bbox.cx
    try:
        from pptx import Presentation

        pages = list(Presentation(str(path)).slides)
    except Exception as error:
        raise CheckUnavailable(f"файл колоды не открылся: {type(error).__name__}") from error
    if len(pages) < len(ctx.deck.slides):
        raise CheckUnavailable(
            f"в файле {len(pages)} слайдов, а в IR {len(ctx.deck.slides)}: страницу не найти"
        )

    for page, slide in zip(pages, ctx.deck.slides, strict=False):
        tables, groups = _frames_on(page)
        for block in slide.blocks:
            box = getattr(block, "bbox", None)
            if box is None:
                continue
            if isinstance(block, TableBlock | ChartBlock):
                frame = next(
                    (t for t in tables if abs(t[0] - box.x) <= near and abs(t[1] - box.y) <= near),
                    None,
                )
                if frame is None or frame[3] <= box.cy * (1 + tolerance):
                    continue
                kind = (
                    "Таблица" if isinstance(block, TableBlock) else "Диаграмма, ставшая таблицей,"
                )
                yield make_finding(
                    check_id="layout.object_overflow",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=box,
                    reason="table_taller",
                    message=(
                        f"{kind} {block.block_id} выше своего места: {emu_to_cm(frame[3]):.1f} см "
                        f"при {emu_to_cm(box.cy):.1f} см"
                    ),
                    evidence={"frame_cy": str(frame[3]), "box_cy": str(box.cy)},
                )
            elif isinstance(block, SmartArtBlock):
                measured = slide.fit_report.get(block.block_id)
                if measured is None or not measured.overflow:
                    continue
                labels = {_plain(item) for item in block.items}
                if not any(labels <= group for group in groups):
                    continue
                yield make_finding(
                    check_id="layout.object_overflow",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=box,
                    reason="smartart_measured",
                    message=(
                        f"Подписи схемы {block.block_id} ({block.pattern.value}) не помещаются "
                        f"в узлы на кегле {measured.final_size_pt:g} pt, а схема записана как есть"
                    ),
                    evidence={"source": "fit_report", "pattern": block.pattern.value},
                )


# --- текст за плашкой (план Б, круг 3, C4; change `a-text-beyond-its-plate`) --------------

def _inset(body: Any, key: str, default: int) -> int:
    """Отступ рамки из `a:bodyPr`; нет его — умолчание OOXML (`TEXT_FRAME_INSET_*`)."""
    value = body.get(key) if body is not None else None
    return int(value) if value is not None and str(value).lstrip("-").isdigit() else default


def _is_filled(node: Any) -> bool:
    """Залита ли фигура: явной заливкой в `spPr` или по стилю темы (`p:style/a:fillRef`),
    если заливка не снята `a:noFill`."""
    from pptx.oxml.ns import qn

    props = node.find(qn("p:spPr"))
    if props is not None:
        if any(props.find(qn(tag)) is not None for tag in ("a:solidFill", "a:gradFill",
                                                           "a:pattFill", "a:blipFill")):
            return True
        if props.find(qn("a:noFill")) is not None:
            return False
    ref = node.find(f"{qn('p:style')}/{qn('a:fillRef')}")
    return ref is not None and ref.get("idx", "0") != "0"


def _text_height(shape: Any, manifest: Any, fonts: Any) -> tuple[int, str]:
    """Высота текста фигуры шрифтом, с её отступами; и якорь (`t`, `ctr`, `b`)."""
    from pptx.oxml.ns import qn

    from deckforge.layout.metrics import line_height_emu, measure_text
    from deckforge.rendering.theme_binding import font_family_for_token

    body = shape._element.find(".//" + qn("a:bodyPr"))
    left = _inset(body, "lIns", TEXT_FRAME_INSET_X_EMU)
    right = _inset(body, "rIns", TEXT_FRAME_INSET_X_EMU)
    top = _inset(body, "tIns", TEXT_FRAME_INSET_Y_EMU)
    bottom = _inset(body, "bIns", TEXT_FRAME_INSET_Y_EMU)
    width = max(1, int(shape.width) - left - right + 2 * TEXT_FRAME_INSET_X_EMU)
    body_step = manifest.typography(TextRole.BODY)
    fallback_pt = body_step.size_pt if body_step is not None else 18.0
    total = 0.0
    for paragraph in shape.text_frame.paragraphs:
        runs = list(paragraph.runs)
        size = next((run.font.size.pt for run in runs if run.font.size), None) or fallback_pt
        face = next((run.font.name for run in runs if run.font.name), None) or "+mn-lt"
        family = font_family_for_token(face, manifest) or face
        measured = measure_text(
            paragraph.text or " ", font_family=family, size_pt=size,
            box=BBox(x=0, y=0, cx=width, cy=1), bold=False, fonts=fonts,
        )
        total += measured.height_emu or line_height_emu(size)
    anchor = (body.get("anchor") if body is not None else None) or "t"
    return round(total) + top + bottom, anchor


@check(
    id="layout.text_beyond_plate",
    deterministic=True,
    severity=Severity.ERROR,
    title="Текст вышел за свою плашку",
)
def text_beyond_plate(ctx: CheckContext) -> Iterable[Finding]:
    """Текст вышел за свою плашку (план Б, круг 3, C4 — мерило B2).

    Прогон `a3a8f3a2319b`, WorkSpace s03: карточка — сама текстовая фигура с заливкой и верхним
    отступом под иконку (`tIns` 756 000 EMU). Вписывание намерило 4 строки и сравнило их
    с высотой зоны без отступа — «влезло», а на слайде последняя строка ушла за край карточки.
    Ни `layout.text_overflow` (верит вписыванию), ни `layout.object_overflow` этого не видели.

    Меряется **готовый файл**: текст — шрифтом (`measure_text`) по ширине фигуры за вычетом её
    отступов, плюс её верхний и нижний отступ, её кеглем, с её якорем. Плашка — сама фигура,
    если у неё есть заливка, иначе наименьшая залитая фигура страницы, в которой лежит угол
    текстовой. Судится только наш текст — фигуры зон рецепта; без плашки — не эта проверка.
    """
    path = ctx.deck_path
    if path is None:
        raise CheckUnavailable("файла колоды ещё нет: вылет текста виден только в .pptx")
    recipes = catalogue(ctx)
    ours = {
        number: {zone.xml_id for zone in recipes[slide.recipe_id].zones if zone.xml_id}
        for number, slide in enumerate(ctx.deck.slides)
        if slide.recipe_id in recipes
    }
    if not ours:
        raise CheckUnavailable("ни одного слайда по рецепту: наших плашек примера нет")
    try:
        from pptx import Presentation

        pages = list(Presentation(str(path)).slides)
    except Exception as error:
        raise CheckUnavailable(f"файл колоды не открылся: {type(error).__name__}") from error
    if len(pages) < len(ctx.deck.slides):
        raise CheckUnavailable(
            f"в файле {len(pages)} слайдов, а в IR {len(ctx.deck.slides)}: страницу не найти"
        )

    from deckforge.layout.fonts import FontLibrary

    fonts = FontLibrary.default()
    tolerance = ctx.param("overflow_share", 0.03)
    for number, zone_ids in ours.items():
        page, slide = pages[number], ctx.deck.slides[number]
        shapes = list(page.shapes)
        for shape in shapes:
            if shape.shape_id not in zone_ids or not getattr(shape, "has_text_frame", False):
                continue
            if not shape.text_frame.text.strip():
                continue
            if _is_filled(shape._element):
                plate = shape
            else:
                under = [
                    other for other in shapes
                    if other is not shape and _is_filled(other._element)
                    and other.left <= shape.left < other.left + other.width
                    and other.top <= shape.top < other.top + other.height
                ]
                if not under:
                    continue
                plate = min(under, key=lambda other: int(other.width) * int(other.height))
            need, anchor = _text_height(shape, ctx.manifest, fonts)
            top = int(shape.top)
            if anchor == "b":
                top = int(shape.top) + int(shape.height) - need
            elif anchor == "ctr":
                top = int(shape.top) + (int(shape.height) - need) // 2
            beyond = top + need - (int(plate.top) + int(plate.height))
            if beyond <= tolerance * int(plate.height):
                continue
            yield make_finding(
                check_id="layout.text_beyond_plate",
                slide_id=slide.slide_id,
                reason=f"plate:{shape.shape_id}",
                message=(
                    f"Текст фигуры {shape.shape_id} выходит за её плашку на "
                    f"{emu_to_cm(beyond):.1f} см ({beyond / int(plate.height):.0%} высоты)"
                ),
                evidence={
                    "shape_id": str(shape.shape_id),
                    "beyond_emu": str(beyond),
                    "plate_cy": str(int(plate.height)),
                },
            )
