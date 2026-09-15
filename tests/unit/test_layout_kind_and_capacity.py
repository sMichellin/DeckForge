"""Классификация макетов и расчёт вместимости. Changes (3) и (5).

Главное, что проверяется: вид макета выводится из геометрии, а **имя макета не участвует**.
Имена в шаблонах произвольны и на разных языках — опора на них это заточка под шаблон (C6).
"""

from __future__ import annotations

from deckforge.domain.enums import ColorRef, FontRef, LayoutKind, TextRole
from deckforge.domain.template import PlaceholderSpec, SlideSize, TypographyStep
from deckforge.parsing.capacity import chars_that_fit, compute_capacity, lines_that_fit
from deckforge.parsing.layout_kind import classify_heuristic, needs_vlm

SLIDE = SlideSize(cx_emu=12_192_000, cy_emu=6_858_000, aspect="16:9")
AREA = SLIDE.cx_emu * SLIDE.cy_emu

SCALE = [
    TypographyStep(role=TextRole.TITLE, size_pt=40, font_ref=FontRef.MAJOR_LATIN,
                   color_ref=ColorRef.DK1),
    TypographyStep(role=TextRole.SUBTITLE, size_pt=24, font_ref=FontRef.MINOR_LATIN,
                   color_ref=ColorRef.DK2),
    TypographyStep(role=TextRole.BODY, size_pt=18, font_ref=FontRef.MINOR_LATIN,
                   color_ref=ColorRef.DK1),
    TypographyStep(role=TextRole.CAPTION, size_pt=12, font_ref=FontRef.MINOR_LATIN,
                   color_ref=ColorRef.DK2),
]


def ph(idx: int, ph_type: str, x: int, y: int, cx: int, cy: int,
       role: TextRole | None = None) -> PlaceholderSpec:
    return PlaceholderSpec(idx=idx, ph_type=ph_type, role=role, x=x, y=y, cx=cx, cy=cy)


TITLE = ph(0, "TITLE", 600_000, 400_000, 10_900_000, 1_000_000, TextRole.TITLE)


# --- классификация -----------------------------------------------------------


def test_explicit_chart_placeholder_wins() -> None:
    kind, confidence = classify_heuristic(
        [TITLE, ph(1, "CHART", 600_000, 1_800_000, 10_900_000, 4_000_000)], SLIDE
    )
    assert kind is LayoutKind.CHART and confidence > 0.9


def test_explicit_table_placeholder_wins() -> None:
    kind, _ = classify_heuristic(
        [TITLE, ph(1, "TBL", 600_000, 1_800_000, 10_900_000, 4_000_000)], SLIDE
    )
    assert kind is LayoutKind.TABLE


def test_large_picture_is_image_full() -> None:
    kind, _ = classify_heuristic([ph(1, "PIC", 0, 0, SLIDE.cx_emu, SLIDE.cy_emu)], SLIDE)
    assert kind is LayoutKind.IMAGE_FULL


def test_title_with_subtitle_is_a_title_slide() -> None:
    kind, _ = classify_heuristic(
        [TITLE, ph(1, "SUBTITLE", 600_000, 1_600_000, 8_000_000, 600_000, TextRole.SUBTITLE)],
        SLIDE,
    )
    assert kind is LayoutKind.TITLE


def test_lonely_centred_title_is_a_section() -> None:
    centred = ph(0, "TITLE", 600_000, 2_900_000, 10_900_000, 1_000_000, TextRole.TITLE)
    kind, _ = classify_heuristic([centred], SLIDE)
    assert kind is LayoutKind.SECTION


def test_title_plus_tall_body_is_bullets() -> None:
    kind, _ = classify_heuristic(
        [TITLE, ph(1, "BODY", 600_000, 1_800_000, 10_900_000, 4_000_000, TextRole.BODY)], SLIDE
    )
    assert kind is LayoutKind.BULLETS


def test_two_bodies_in_a_row_are_two_columns() -> None:
    kind, _ = classify_heuristic(
        [
            TITLE,
            ph(1, "BODY", 600_000, 1_800_000, 5_200_000, 4_000_000, TextRole.BODY),
            ph(2, "BODY", 6_400_000, 1_800_000, 5_200_000, 4_000_000, TextRole.BODY),
        ],
        SLIDE,
    )
    assert kind is LayoutKind.TWO_COLUMN


def test_three_small_blocks_in_a_row_are_kpi() -> None:
    row = [
        ph(i + 1, "BODY", 600_000 + i * 3_700_000, 2_800_000, 3_400_000, 900_000, TextRole.BODY)
        for i in range(3)
    ]
    kind, _ = classify_heuristic([TITLE, *row], SLIDE)
    assert kind is LayoutKind.KPI


def test_footers_do_not_make_a_layout_meaningful() -> None:
    """Колонтитул и номер слайда есть почти везде и ничего не говорят о виде макета."""
    decor = [
        ph(11, "FTR", 600_000, 6_400_000, 3_000_000, 200_000, TextRole.CAPTION),
        ph(12, "SLDNUM", 11_000_000, 6_400_000, 500_000, 200_000, TextRole.CAPTION),
    ]
    with_decor, _ = classify_heuristic([TITLE, *decor], SLIDE)
    without_decor, _ = classify_heuristic([TITLE], SLIDE)
    assert with_decor is without_decor


def test_empty_layout_gets_low_confidence() -> None:
    _, confidence = classify_heuristic([], SLIDE)
    assert needs_vlm(confidence), "пустой макет обязан уйти на доклассификацию VLM"


def test_uncertain_results_are_routed_to_vlm() -> None:
    assert needs_vlm(0.3) and not needs_vlm(0.9)


# --- вместимость -------------------------------------------------------------


def test_capacity_scales_with_area() -> None:
    small = ph(1, "BODY", 0, 0, 3_000_000, 1_000_000, TextRole.BODY)
    large = ph(1, "BODY", 0, 0, 9_000_000, 4_000_000, TextRole.BODY)
    assert chars_that_fit(large, 18) > chars_that_fit(small, 18)
    assert lines_that_fit(large, 18) > lines_that_fit(small, 18)


def test_bigger_font_fits_fewer_characters() -> None:
    box = ph(1, "BODY", 0, 0, 9_000_000, 4_000_000, TextRole.BODY)
    assert chars_that_fit(box, 40) < chars_that_fit(box, 12)


def test_capacity_is_computed_not_constant() -> None:
    body = ph(1, "BODY", 600_000, 1_800_000, 10_900_000, 4_000_000, TextRole.BODY)
    capacity = compute_capacity([TITLE, body], SCALE, AREA)
    assert capacity.max_bullets > 0
    assert capacity.max_chars_body > 0
    assert capacity.max_chars_title > 0
    assert capacity.supports_chart and capacity.supports_table


def test_narrow_strip_does_not_support_a_chart() -> None:
    strip = ph(1, "BODY", 600_000, 6_000_000, 10_900_000, 250_000, TextRole.BODY)
    capacity = compute_capacity([TITLE, strip], SCALE, AREA)
    assert not capacity.supports_chart


def test_layout_without_content_placeholders_has_zero_capacity() -> None:
    """Так выглядит реальный шаблон, рассчитанный на ручное наполнение: это не ошибка."""
    capacity = compute_capacity([TITLE], SCALE, AREA)
    assert capacity.max_bullets == 0 and capacity.max_chars_body == 0
    assert capacity.max_chars_title > 0
