"""Чистые правила домена: контраст, пересечения, шкала кеглей, выбор диаграммы."""

from __future__ import annotations

import pytest

from deckforge.domain.base import BBox
from deckforge.domain.enums import ChartType, ColorRef
from deckforge.domain.rules import (
    choose_chart_type,
    contrast_ratio,
    delta_e_rgb,
    fill_ratio,
    meets_wcag_aa,
    next_size_down,
    overlap_ratio,
    readable_text_ref,
    snap_to_nearest,
)
from deckforge.domain.template import TemplateManifest


def test_contrast_extremes() -> None:
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0, abs=0.01)


def test_contrast_is_symmetric() -> None:
    assert contrast_ratio("#2E6BE6", "#FFFFFF") == pytest.approx(
        contrast_ratio("#FFFFFF", "#2E6BE6")
    )


def test_readable_text_ref_follows_the_background(manifest: TemplateManifest) -> None:
    """Цвет свободного текста выбирается измерением, а не таблицей соответствий."""
    colors = manifest.theme.colors
    assert readable_text_ref(manifest, colors.get(ColorRef.DK1)) is ColorRef.LT1
    assert readable_text_ref(manifest, colors.get(ColorRef.LT1)) is ColorRef.DK1


def test_readable_text_ref_beats_the_wcag_threshold(manifest: TemplateManifest) -> None:
    """Выбранный слот обязан не просто отличаться от фона, а читаться на нём."""
    for background in (ColorRef.DK1, ColorRef.LT1, ColorRef.DK2, ColorRef.LT2):
        hex_bg = manifest.theme.colors.get(background)
        chosen = manifest.theme.colors.get(readable_text_ref(manifest, hex_bg))
        assert meets_wcag_aa(chosen, hex_bg), background


def test_wcag_thresholds() -> None:
    assert meets_wcag_aa("#000000", "#FFFFFF")
    assert not meets_wcag_aa("#BBBBBB", "#FFFFFF")
    # крупный текст проходит по более мягкому порогу 3:1
    assert meets_wcag_aa("#949494", "#FFFFFF", large_text=True)
    assert not meets_wcag_aa("#949494", "#FFFFFF", large_text=False)


def test_delta_e_zero_for_same_color() -> None:
    assert delta_e_rgb("#2E6BE6", "#2E6BE6") == 0.0
    assert delta_e_rgb("#000000", "#FFFFFF") > 400


def test_overlap_ratio_uses_smaller_block() -> None:
    big = BBox(x=0, y=0, cx=100, cy=100)
    small = BBox(x=0, y=0, cx=10, cy=10)
    assert overlap_ratio(big, small) == pytest.approx(1.0)
    assert overlap_ratio(big, BBox(x=500, y=500, cx=10, cy=10)) == 0.0


def test_snap_respects_tolerance() -> None:
    guides = [0, 1000, 2000]
    assert snap_to_nearest(1010, guides, tolerance_emu=50) == 1000
    assert snap_to_nearest(1500, guides, tolerance_emu=50) == 1500
    assert snap_to_nearest(1500, [], tolerance_emu=50) == 1500


def test_next_size_down_uses_template_ladder(manifest: TemplateManifest) -> None:
    """Кегли берутся из шаблона, свои значения не изобретаются (ADR-002)."""
    assert next_size_down(manifest, 40) == 24
    assert next_size_down(manifest, 24) == 18
    assert next_size_down(manifest, 12) is None


def test_chart_choice_is_deterministic() -> None:
    assert choose_chart_type(
        series_count=1, category_count=4, is_time_series=False, is_shares=True
    ) is ChartType.DOUGHNUT
    assert choose_chart_type(
        series_count=2, category_count=8, is_time_series=True, is_shares=False
    ) is ChartType.LINE_MARKERS
    assert choose_chart_type(
        series_count=3, category_count=5, is_time_series=False, is_shares=False
    ) is ChartType.CLUSTERED_COLUMN
    assert choose_chart_type(
        series_count=1, category_count=20, is_time_series=False, is_shares=False
    ) is ChartType.CLUSTERED_BAR


def test_fill_ratio() -> None:
    slide = BBox(x=0, y=0, cx=100, cy=100)
    assert fill_ratio([BBox(x=0, y=0, cx=50, cy=50)], slide) == pytest.approx(0.25)
    assert fill_ratio([], slide) == 0.0
