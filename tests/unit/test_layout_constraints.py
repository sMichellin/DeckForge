"""Раскладка блоков без плейсхолдера. Change (12) `layout-fitting`."""

from __future__ import annotations

import itertools

import pytest

from deckforge.domain.base import BBox
from deckforge.domain.template import TemplateManifest
from deckforge.layout.constraints import solve_positions
from deckforge.layout.fitting import LayoutFitError


def assert_no_overlap(boxes: dict[str, BBox]) -> None:
    for a, b in itertools.combinations(boxes.values(), 2):
        assert a.intersection_area(b) == 0


def test_no_blocks_no_positions(manifest: TemplateManifest) -> None:
    assert solve_positions([], manifest) == {}


def test_free_blocks_share_the_content_area_in_equal_columns(manifest: TemplateManifest) -> None:
    out = solve_positions([("a", None), ("b", None), ("c", None)], manifest)
    content = manifest.content_bbox
    assert all(content.contains(box) for box in out.values())
    assert_no_overlap(out)
    widths = {box.cx for box in out.values()}
    assert max(widths) - min(widths) <= 1
    assert out["a"].x == content.x
    assert out["c"].right == pytest.approx(content.right, abs=2)
    assert out["b"].x - out["a"].right == pytest.approx(manifest.grid.gutter_emu, abs=1)


def test_single_free_block_fills_the_content_area(manifest: TemplateManifest) -> None:
    assert solve_positions([("a", None)], manifest)["a"] == manifest.content_bbox


def test_fixed_blocks_stay_and_free_ones_avoid_them(manifest: TemplateManifest) -> None:
    content = manifest.content_bbox
    fixed = BBox(x=content.x, y=content.y, cx=content.cx, cy=content.cy // 3)
    out = solve_positions([("fixed", fixed), ("a", None), ("b", None)], manifest)
    assert out["fixed"] == fixed
    assert all(content.contains(box) for box in out.values())
    assert_no_overlap(out)
    assert out["a"].y >= fixed.bottom


def test_scattered_fixed_blocks_leave_room_for_free_ones(manifest: TemplateManifest) -> None:
    """Две метки по углам не должны объявлять занятой всю область между ними."""
    content = manifest.content_bbox
    corner = content.cx // 10, content.cy // 10
    top_left = BBox(x=content.x, y=content.y, cx=corner[0], cy=corner[1])
    bottom_right = BBox(
        x=content.right - corner[0], y=content.bottom - corner[1], cx=corner[0], cy=corner[1]
    )
    out = solve_positions([("tl", top_left), ("br", bottom_right), ("a", None)], manifest)
    assert all(content.contains(box) for box in out.values())
    assert_no_overlap(out)
    assert out["a"].area >= content.area // 2


def test_more_blocks_than_the_band_can_hold_is_a_layout_error(
    manifest: TemplateManifest,
) -> None:
    too_many = manifest.content_bbox.cx // manifest.grid.gutter_emu + 2
    many: list[tuple[str, BBox | None]] = [(f"b{i}", None) for i in range(too_many)]
    with pytest.raises(LayoutFitError):
        solve_positions(many, manifest)


def test_fixed_block_outside_margins_is_rejected(manifest: TemplateManifest) -> None:
    outside = BBox(x=0, y=0, cx=manifest.slide_size.cx_emu, cy=manifest.slide_size.cy_emu)
    with pytest.raises(LayoutFitError):
        solve_positions([("x", outside), ("a", None)], manifest)


def test_no_free_room_is_an_error(manifest: TemplateManifest) -> None:
    with pytest.raises(LayoutFitError):
        solve_positions([("all", manifest.content_bbox), ("a", None)], manifest)
