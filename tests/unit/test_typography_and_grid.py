"""Вывод типошкалы и сетки. Change (4) `theme-extraction`."""

from __future__ import annotations

import pytest

from deckforge.domain.enums import ColorRef, FontRef, LayoutKind, TextRole
from deckforge.domain.template import (
    LayoutCapacity,
    LayoutSpec,
    Margins,
    PlaceholderSpec,
    SlideSize,
    Theme,
)
from deckforge.parsing.grid import cluster_positions, extract_guides, infer_grid, infer_margins
from deckforge.parsing.ooxml.theme import parse_theme
from deckforge.parsing.typography import TypographyObservation, derive_scale
from tests.unit.test_ooxml_theme import theme_xml

SLIDE = SlideSize(cx_emu=12_192_000, cy_emu=6_858_000, aspect="16:9")


@pytest.fixture
def plain_theme() -> Theme:
    return parse_theme(theme_xml({"dk1": "101014", "dk2": "3C4250", "accent1": "0077FF"}))


def obs(role: TextRole, size: float, **kw: object) -> TypographyObservation:
    return TypographyObservation(role=role, size_pt=size, **kw)  # type: ignore[arg-type]


# --- типошкала ---------------------------------------------------------------


def test_representative_size_is_the_most_frequent(plain_theme: Theme) -> None:
    """Среднее сместил бы один нестандартный макет; берём преобладающий кегль."""
    scale = derive_scale(
        [obs(TextRole.TITLE, 24) for _ in range(10)]
        + [obs(TextRole.TITLE, 54), obs(TextRole.BODY, 14)],
        plain_theme,
    )
    assert next(s.size_pt for s in scale if s.role is TextRole.TITLE) == 24


def test_tie_is_broken_towards_the_larger_size(plain_theme: Theme) -> None:
    scale = derive_scale(
        [obs(TextRole.TITLE, 30), obs(TextRole.TITLE, 40), obs(TextRole.BODY, 14)], plain_theme
    )
    assert next(s.size_pt for s in scale if s.role is TextRole.TITLE) == 40


def test_missing_roles_are_derived_and_scale_stays_descending(plain_theme: Theme) -> None:
    """Шаблон может не содержать подзаголовков вовсе — шкала всё равно обязана убывать."""
    scale = derive_scale([obs(TextRole.TITLE, 40), obs(TextRole.BODY, 18)], plain_theme)
    sizes = [s.size_pt for s in scale]
    assert len(scale) == 4
    assert sizes == sorted(sizes, reverse=True)
    assert len(set(sizes)) == 4


def test_scale_recovers_when_only_small_role_is_observed(plain_theme: Theme) -> None:
    scale = derive_scale([obs(TextRole.CAPTION, 10)], plain_theme)
    assert [s.role for s in scale] == list(TextRole)[:4] or len(scale) == 4
    assert next(s.size_pt for s in scale if s.role is TextRole.TITLE) > 10


def test_no_observations_at_all_is_an_error(plain_theme: Theme) -> None:
    with pytest.raises(ValueError, match="кегл"):
        derive_scale([], plain_theme)


def test_colour_is_mapped_to_a_theme_slot_not_stored_as_rgb(plain_theme: Theme) -> None:
    """ADR-002: в шкале живёт ссылка на тему, а не код цвета."""
    scale = derive_scale(
        [obs(TextRole.TITLE, 40, color_hex="#0077FF"), obs(TextRole.BODY, 18)], plain_theme
    )
    assert next(s.color_ref for s in scale if s.role is TextRole.TITLE) is ColorRef.ACCENT1


def test_colour_far_from_palette_falls_back_to_default(plain_theme: Theme) -> None:
    scale = derive_scale([obs(TextRole.TITLE, 40, color_hex="#7B3FA0")], plain_theme)
    assert next(s.color_ref for s in scale if s.role is TextRole.TITLE) is ColorRef.DK1


def test_title_uses_major_font_and_body_minor(plain_theme: Theme) -> None:
    scale = derive_scale([obs(TextRole.TITLE, 40), obs(TextRole.BODY, 18)], plain_theme)
    by_role = {s.role: s for s in scale}
    assert by_role[TextRole.TITLE].font_ref is FontRef.MAJOR_LATIN
    assert by_role[TextRole.BODY].font_ref is FontRef.MINOR_LATIN


def test_bold_follows_the_majority(plain_theme: Theme) -> None:
    scale = derive_scale(
        [obs(TextRole.TITLE, 40, bold=True), obs(TextRole.TITLE, 40, bold=True),
         obs(TextRole.TITLE, 40, bold=False)],
        plain_theme,
    )
    assert next(s.bold for s in scale if s.role is TextRole.TITLE) is True


# --- сетка -------------------------------------------------------------------


def test_cluster_requires_support() -> None:
    """Координата из одного макета — особенность макета, а не направляющая шаблона."""
    assert cluster_positions([100, 105, 5000], tolerance=50, min_support=2) == [102]
    assert cluster_positions([100], tolerance=50, min_support=2) == []
    assert cluster_positions([], tolerance=50, min_support=2) == []


def test_guides_from_view_props_are_converted_and_split_by_axis() -> None:
    xml = (
        b'<p:viewPr xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        b'<p:guide orient="horz" pos="1440"/><p:guide pos="2880"/></p:viewPr>'
    )
    guides = extract_guides(xml)
    assert guides is not None
    xs, ys = guides
    assert ys == [1440 * 12700 // 8] and xs == [2880 * 12700 // 8]


def test_no_view_props_means_guides_must_be_inferred() -> None:
    assert extract_guides(None) is None
    empty = b'<p:viewPr xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>'
    assert extract_guides(empty) is None


def layout(
    *boxes: tuple[int, int, int, int],
    role: TextRole | None = TextRole.BODY,
    kind: LayoutKind = LayoutKind.BULLETS,
) -> LayoutSpec:
    return LayoutSpec(
        layout_id="L00",
        name="проба",
        master="M01",
        part_name="ppt/slideLayouts/slideLayout1.xml",
        index=0,
        kind=kind,
        kind_confidence=0.8,
        kind_source="heuristic",
        capacity=LayoutCapacity(max_bullets=0, max_chars_body=0, max_chars_title=0),
        placeholders=[
            PlaceholderSpec(idx=i, ph_type="BODY", role=role, x=x, y=y, cx=cx, cy=cy)
            for i, (x, y, cx, cy) in enumerate(boxes)
        ],
    )


def test_full_bleed_placeholders_do_not_zero_out_margins() -> None:
    """Полноэкранная плашка — приём шаблона, а не отмена полей для текста."""
    layouts = [
        layout((0, 0, SLIDE.cx_emu, SLIDE.cy_emu)),
        layout((600_000, 400_000, 8_000_000, 3_000_000)),
        layout((600_000, 400_000, 8_000_000, 3_000_000)),
    ]
    margins = infer_margins(layouts, SLIDE)
    assert margins.left == 600_000
    assert margins.top == 400_000


def test_margins_fall_back_when_every_placeholder_is_full_bleed() -> None:
    margins = infer_margins([layout((0, 0, SLIDE.cx_emu, SLIDE.cy_emu))], SLIDE)
    assert margins.left == 0


# --- поля, когда в шаблоне нет ни одного макета с телом контента -----------


def test_margins_fall_back_when_no_layout_has_a_body_kind() -> None:
    """Шаблон из одних обложек и разделителей: единственный источник геометрии
    декоративный, и разные оси по-разному "врут" на нём (см. docstring
    `infer_margins`). Правильный ответ здесь — обычные поля, а не подсчёт
    по декоративным макетам."""
    layouts = [
        layout((429_253, 424_691, 7_827_311, 1_167_572), kind=LayoutKind.TITLE),
        layout((429_253, 2_546_255, 7_827_335, 1_876_890), kind=LayoutKind.IMAGE_FULL),
        layout((429_254, 1_609_196, 4_803_146, 1_876_890), kind=LayoutKind.SECTION),
    ]
    margins = infer_margins(layouts, SLIDE)

    assert margins.left == margins.right, "запасные поля симметричны по X"
    assert margins.top == margins.bottom, "запасные поля симметричны по Y"
    # Геометрия декоративных макетов эту оценку не участвует вовсе.
    assert margins.top not in (424_691, 2_546_255, 1_609_196)


def test_a_single_body_layout_is_enough_to_use_real_geometry() -> None:
    """Одного макета с телом контента достаточно, чтобы не уходить в запасной вариант:
    поля по-прежнему считаются по геометрии плейсхолдеров, а не по доле слайда."""
    layouts = [
        layout((600_000, 400_000, 8_000_000, 3_000_000), kind=LayoutKind.BULLETS),
        layout((429_253, 2_546_255, 7_827_335, 1_876_890), kind=LayoutKind.IMAGE_FULL),
    ]
    fallback = infer_margins(
        [layout((0, 0, 1, 1), kind=LayoutKind.TITLE)], SLIDE
    )  # для сравнения: чем должен НЕ стать результат
    margins = infer_margins(layouts, SLIDE)
    assert margins.top == 400_000, "минимум по Y берётся из плейсхолдеров, а не из доли слайда"
    assert margins != Margins(
        left=fallback.left, right=fallback.left, top=fallback.top, bottom=fallback.top
    )


def test_grid_prefers_explicit_guides_and_records_the_source() -> None:
    layouts = [layout((600_000, 400_000, 8_000_000, 3_000_000))] * 2
    xml = (
        b'<p:viewPr xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        b'<p:guide pos="2880"/></p:viewPr>'
    )
    assert infer_grid(layouts, SLIDE, xml).guides_source == "xml"
    assert infer_grid(layouts, SLIDE, None).guides_source == "inferred"


def test_inferred_guides_pick_up_repeated_edges() -> None:
    layouts = [layout((600_000, 400_000, 8_000_000, 3_000_000))] * 3
    grid = infer_grid(layouts, SLIDE, None)
    assert 600_000 in grid.guides_x_emu
    assert grid.columns > 0
