"""Геометрия составных компонентов и вписывание их текста. Change (21) `smartart-icons`."""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.base import BBox
from deckforge.domain.enums import SmartArtPattern
from deckforge.domain.slide import SlideIR, SmartArtBlock, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.domain.units import EMU_PER_CM
from deckforge.layout.diagram import SUPPORTED_PATTERNS, diagram_geometry
from deckforge.layout.errors import LayoutFitError
from deckforge.layout.fitting import fit_slide, fit_smartart
from deckforge.layout.fonts import FontLibrary
from tests.unit.test_layout_fonts import make_font

BOX = BBox(x=2 * EMU_PER_CM, y=5 * EMU_PER_CM, cx=30 * EMU_PER_CM, cy=10 * EMU_PER_CM)


def overlaps(a: BBox, b: BBox) -> bool:
    return a.intersection_area(b) > 0


# --- геометрия ------------------------------------------------------------------


@pytest.mark.parametrize("pattern", sorted(SUPPORTED_PATTERNS))
@pytest.mark.parametrize("count", [2, 3, 5, 8])
def test_every_part_stays_inside_the_box_and_nodes_do_not_overlap(
    pattern: SmartArtPattern, count: int
) -> None:
    geometry = diagram_geometry(pattern, count, BOX)
    assert len(geometry.nodes) == len(geometry.labels) == count
    for part in [*geometry.nodes, *geometry.labels]:
        assert BOX.contains(part)
    for link in geometry.links:
        for x, y in ((link.x1, link.y1), (link.x2, link.y2)):
            assert BOX.x <= x <= BOX.right and BOX.y <= y <= BOX.bottom
    for i, a in enumerate(geometry.nodes):
        for b in geometry.nodes[i + 1:]:
            assert not overlaps(a, b)
    for i, a in enumerate(geometry.labels):
        for b in geometry.labels[i + 1:]:
            assert not overlaps(a, b)


def test_process_goes_left_to_right_with_an_arrow_between_neighbours() -> None:
    geometry = diagram_geometry(SmartArtPattern.PROCESS, 3, BOX)
    xs = [node.x for node in geometry.nodes]
    assert xs == sorted(xs)
    assert geometry.nodes[0].x == BOX.x
    assert 0 <= BOX.right - geometry.nodes[-1].right < len(geometry.nodes)
    # Текст скруглённого прямоугольника PowerPoint кладёт внутрь скругления:
    # отступ = min(w, h) × 16667 / 100000 × (1 − 1/√2) (presetShapeDefinitions, roundRect).
    for node, label in zip(geometry.nodes, geometry.labels, strict=True):
        inset = round(min(node.cx, node.cy) * 0.16667 * (1 - 2**-0.5))
        assert abs(label.x - (node.x + inset)) <= 1 and abs(label.y - (node.y + inset)) <= 1
        assert abs(label.cx - (node.cx - 2 * inset)) <= 2
    assert len(geometry.links) == 2
    first, second = geometry.nodes[:2]
    link = geometry.links[0]
    assert first.right <= link.x1 < link.x2 <= second.x
    assert link.y1 == link.y2 == first.y + first.cy // 2


def test_timeline_puts_markers_on_one_axis_and_labels_under_them() -> None:
    geometry = diagram_geometry(SmartArtPattern.TIMELINE, 4, BOX)
    assert len({node.y for node in geometry.nodes}) == 1
    assert len(geometry.links) == 1
    axis = geometry.links[0]
    marker = geometry.nodes[0]
    assert axis.y1 == axis.y2 == marker.y + marker.cy // 2
    assert axis.x1 == BOX.x and axis.x2 == BOX.right
    for node, label in zip(geometry.nodes, geometry.labels, strict=True):
        assert node.cx == node.cy
        assert label.y >= node.bottom
        assert label.x <= node.x and node.right <= label.right


def test_cycle_closes_the_loop_around_the_centre() -> None:
    geometry = diagram_geometry(SmartArtPattern.CYCLE, 4, BOX)
    assert len(geometry.links) == 4
    centre_y = BOX.y + BOX.cy // 2
    top = geometry.nodes[0]
    assert top.y == min(node.y for node in geometry.nodes)
    assert top.y + top.cy // 2 < centre_y
    assert geometry.text_inside


def test_cycle_in_a_wide_box_uses_the_width() -> None:
    """Круги по короткой стороне оставляли под текст квадратик в сантиметр: узлы цикла —
    прямоугольники на эллиптической орбите, растянутые по ширине рамки."""
    geometry = diagram_geometry(SmartArtPattern.CYCLE, 4, BOX)
    node = geometry.nodes[0]
    assert node.cx > node.cy
    assert node.cx > BOX.cx // 4
    xs = [n.x for n in geometry.nodes]
    assert min(xs) == BOX.x and max(n.right for n in geometry.nodes) <= BOX.right
    assert BOX.right - max(n.right for n in geometry.nodes) <= 1


def test_cycle_in_a_square_box_has_square_nodes() -> None:
    square = BBox(x=BOX.x, y=BOX.y, cx=BOX.cy, cy=BOX.cy)
    for node in diagram_geometry(SmartArtPattern.CYCLE, 5, square).nodes:
        assert abs(node.cx - node.cy) <= 1


def test_unsupported_pattern_is_an_error() -> None:
    with pytest.raises(LayoutFitError, match="hierarchy"):
        diagram_geometry(SmartArtPattern.HIERARCHY, 3, BOX)


# --- вписывание -----------------------------------------------------------------


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=500, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=500)
    return FontLibrary([tmp_path])


def smartart(pattern: str, items: list[str], box: BBox = BOX) -> SmartArtBlock:
    return SmartArtBlock(block_id="sa", pattern=pattern, items=items,
                         x=box.x, y=box.y, cx=box.cx, cy=box.cy)


def test_short_labels_fit_at_the_body_size(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    block = smartart("process", ["Сбор", "Анализ", "Решение"])
    fit = fit_smartart(block, BOX, manifest, fonts=fonts)
    assert not fit.overflow
    assert fit.final_size_pt == 18
    assert fit.strategy == "as_is"


def test_one_long_label_shrinks_every_node_to_the_same_step(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    narrow = BBox(x=BOX.x, y=BOX.y, cx=BOX.cx, cy=2 * EMU_PER_CM)
    long = "Согласование бюджета с юристами и финансовым блоком компании"
    fit = fit_smartart(smartart("process", ["Сбор", long, "Решение"], narrow), narrow, manifest,
                       fonts=fonts)
    assert fit.final_size_pt < 18
    assert fit.final_size_pt in manifest.size_ladder_pt


def test_text_that_never_fits_is_an_overflow(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    tiny = BBox(x=BOX.x, y=BOX.y, cx=6 * EMU_PER_CM, cy=EMU_PER_CM)
    fit = fit_smartart(smartart("cycle", ["очень длинная подпись " * 5] * 3, tiny), tiny,
                       manifest, fonts=fonts)
    assert fit.overflow


def test_fit_slide_reports_smartart(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    slide = SlideIR(
        slide_id="s", layout_id="L07", variant="A",
        blocks=[TextBlock(block_id="t", placeholder_idx=0, role="title", text="Процесс"),
                smartart("timeline", ["2024", "2025", "2026"])],
    )
    report = fit_slide(slide, manifest, fonts=fonts).fit_report
    assert set(report) == {"t", "sa"}


def test_smartart_without_coordinates_is_an_error(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    slide = SlideIR(
        slide_id="s", layout_id="L07", variant="A",
        blocks=[SmartArtBlock(block_id="sa", pattern="process", items=["а", "б"])],
    )
    with pytest.raises(LayoutFitError, match="координат"):
        fit_slide(slide, manifest, fonts=fonts)


def test_unsupported_pattern_is_not_fitted(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    """Такой блок писатель заменит буллетами и впишет их сам."""
    slide = SlideIR(slide_id="s", layout_id="L07", variant="A",
                    blocks=[smartart("pyramid", ["а", "б"])])
    assert fit_slide(slide, manifest, fonts=fonts).fit_report == {}


def test_a_word_is_never_broken_inside_a_node(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Высота разорванного слова влезает, но «Прове/ркам» в узле выглядит браком:
    кегль уменьшается, пока каждое слово не встанет в строку целиком."""
    box = BBox(x=BOX.x, y=BOX.y, cx=12 * EMU_PER_CM, cy=5 * EMU_PER_CM)
    fit = fit_smartart(smartart("process", ["План", "Проверками", "Итог"], box), box, manifest,
                       fonts=fonts)
    assert fit.final_size_pt == 12
    assert not fit.overflow


def test_a_word_wider_than_the_node_at_every_size_is_an_overflow(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    box = BBox(x=BOX.x, y=BOX.y, cx=12 * EMU_PER_CM, cy=5 * EMU_PER_CM)
    fit = fit_smartart(smartart("process", ["Корректировками", "б", "в"], box), box, manifest,
                       fonts=fonts)
    assert fit.overflow


def segment_hits(link: object, box: BBox) -> bool:
    """Пересекает ли отрезок внутренность прямоугольника (отсечение Лианга — Барски)."""
    x1, y1, x2, y2 = link  # type: ignore[misc]
    low, high = 0.0, 1.0
    for p, q in ((-(x2 - x1), x1 - box.x), (x2 - x1, box.right - x1),
                 (-(y2 - y1), y1 - box.y), (y2 - y1, box.bottom - y1)):
        if p == 0:
            if q <= 0:
                return False
        elif p < 0:
            low = max(low, q / p)
        else:
            high = min(high, q / p)
    return low < high


@pytest.mark.parametrize("count", [3, 4, 5, 6])
@pytest.mark.parametrize("cy", [1_800_000, 3_600_000])
def test_cycle_arrows_never_cross_other_nodes(count: int, cy: int) -> None:
    """В вытянутой полосе стрелка 2 → 3 шла сквозь верхний узел, и цикл читался как 2 → 1 → 3."""
    strip = BBox(x=0, y=0, cx=11_000_000, cy=cy)
    geometry = diagram_geometry(SmartArtPattern.CYCLE, count, strip)
    assert len(geometry.links) == count
    for i, link in enumerate(geometry.links):
        ends = {i, (i + 1) % count}
        for j, node in enumerate(geometry.nodes):
            if j not in ends:
                assert not segment_hits(link, node), (i, j)


def test_cycle_of_two_has_arrows_both_ways_side_by_side() -> None:
    geometry = diagram_geometry(SmartArtPattern.CYCLE, 2, BOX)
    there, back = geometry.links
    assert there.y1 < there.y2 and back.y1 > back.y2
    assert there.x1 != back.x1


def test_process_card_is_not_taller_than_it_is_wide() -> None:
    """Прогон 693d464d54fb, s04: четыре карточки 4,4 × 12 см — это столбы, а не шаги.

    Рамку блоку отдаёт решатель целиком, и растягивать по ней карточку значит
    принимать границу свободной площади за решение о размере фигуры.
    """
    tall = BBox(x=2 * EMU_PER_CM, y=3 * EMU_PER_CM, cx=21 * EMU_PER_CM, cy=12 * EMU_PER_CM)
    diagram = diagram_geometry(SmartArtPattern.PROCESS, 4, tall)

    for node in diagram.nodes:
        assert node.cy <= node.cx, "карточка выше своей ширины"


def test_process_row_is_centred_in_the_frame() -> None:
    """Ряд, прижатый к верхнему краю, оставил бы под собой пустое поле."""
    tall = BBox(x=2 * EMU_PER_CM, y=3 * EMU_PER_CM, cx=21 * EMU_PER_CM, cy=12 * EMU_PER_CM)
    diagram = diagram_geometry(SmartArtPattern.PROCESS, 4, tall)

    node = diagram.nodes[0]
    above, below = node.y - tall.y, tall.bottom - node.bottom
    assert abs(above - below) <= EMU_PER_CM // 10, "ряд стоит не по середине рамки"


def test_process_in_a_flat_frame_keeps_the_frame_height() -> None:
    """Рамка ниже карточки — потолок: расширять её за отведённое нельзя."""
    flat = BBox(x=2 * EMU_PER_CM, y=3 * EMU_PER_CM, cx=21 * EMU_PER_CM, cy=2 * EMU_PER_CM)
    diagram = diagram_geometry(SmartArtPattern.PROCESS, 4, flat)

    assert all(node.cy == flat.cy for node in diagram.nodes)


def test_matrix_of_four_is_a_two_by_two_grid_without_arrows() -> None:
    """Перечисление — не шаги: стрелки процесса соврали бы о порядке, которого нет."""
    diagram = diagram_geometry(SmartArtPattern.MATRIX, 4, BOX)

    assert diagram.links == () and diagram.arrows is False
    assert len({node.y for node in diagram.nodes}) == 2, "не два ряда"
    assert len({node.x for node in diagram.nodes}) == 2, "не две колонки"
    assert all(node.cy <= node.cx for node in diagram.nodes)


def test_short_last_row_of_the_matrix_is_centred() -> None:
    """Пять плиток: три сверху и две снизу — нижний ряд по центру, а не у левого края."""
    diagram = diagram_geometry(SmartArtPattern.MATRIX, 5, BOX)
    top = [node for node in diagram.nodes if node.y == diagram.nodes[0].y]
    bottom = [node for node in diagram.nodes if node.y != diagram.nodes[0].y]

    assert (len(top), len(bottom)) == (3, 2)
    left_gap = bottom[0].x - BOX.x
    right_gap = BOX.right - bottom[-1].right
    assert abs(left_gap - right_gap) <= EMU_PER_CM // 10


def test_matrix_grid_stands_in_the_middle_of_the_frame() -> None:
    tall = BBox(x=2 * EMU_PER_CM, y=3 * EMU_PER_CM, cx=21 * EMU_PER_CM, cy=12 * EMU_PER_CM)
    diagram = diagram_geometry(SmartArtPattern.MATRIX, 4, tall)
    above = diagram.nodes[0].y - tall.y
    below = tall.bottom - max(node.bottom for node in diagram.nodes)

    assert abs(above - below) <= EMU_PER_CM // 10
