"""Замер текста настоящими метриками гарнитуры. Change (12) `layout-fitting`."""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.base import BBox
from deckforge.domain.units import EMU_PER_PT, TEXT_FRAME_INSET_X_EMU, TEXT_FRAME_INSET_Y_EMU
from deckforge.layout.fonts import FontLibrary
from deckforge.layout.metrics import LINE_HEIGHT_RATIO, measure_text
from tests.unit.test_layout_fonts import make_font

SIZE_PT = 10.0
#: Ширина знака синтетического шрифта при кегле 10 pt и advance 500/1000.
CHAR_EMU = int(0.5 * SIZE_PT * EMU_PER_PT)


@pytest.fixture
def fonts(tmp_path: Path) -> FontLibrary:
    make_font(tmp_path, "Deck Sans", advance=500)
    return FontLibrary([tmp_path])


def box_for_chars(n: int, lines: int = 20) -> BBox:
    """Рамка, в полезную ширину которой входит ровно `n` знаков."""
    line_emu = LINE_HEIGHT_RATIO * SIZE_PT * EMU_PER_PT
    return BBox(
        x=0,
        y=0,
        cx=n * CHAR_EMU + 2 * TEXT_FRAME_INSET_X_EMU,
        cy=int(lines * line_emu) + 2 * TEXT_FRAME_INSET_Y_EMU,
    )


def measure(text: str, box: BBox, fonts: FontLibrary, **kw: float) -> tuple[int, int, int]:
    m = measure_text(text, font_family="Deck Sans", size_pt=SIZE_PT, box=box, fonts=fonts, **kw)
    return m.lines, m.width_emu, m.height_emu


def test_short_text_takes_one_line(fonts: FontLibrary) -> None:
    lines, width, _ = measure("абв", box_for_chars(10), fonts)
    assert lines == 1
    assert width == 3 * CHAR_EMU


def test_words_wrap_at_spaces_not_inside_words(fonts: FontLibrary) -> None:
    """«аааа бббб» в строку на 6 знаков: второе слово целиком уходит вниз."""
    lines, width, _ = measure("аааа бббб", box_for_chars(6), fonts)
    assert lines == 2
    assert width == 4 * CHAR_EMU


def test_exact_fit_does_not_wrap(fonts: FontLibrary) -> None:
    assert measure("ааа ббб", box_for_chars(7), fonts)[0] == 1


def test_word_longer_than_line_breaks_by_characters(fonts: FontLibrary) -> None:
    assert measure("а" * 25, box_for_chars(10), fonts)[0] == 3


def test_paragraphs_and_line_breaks_start_new_lines(fonts: FontLibrary) -> None:
    assert measure("а\nб\vв", box_for_chars(10), fonts)[0] == 3


def test_empty_paragraph_still_takes_a_line(fonts: FontLibrary) -> None:
    assert measure("а\n\nб", box_for_chars(10), fonts)[0] == 3


def test_trailing_space_does_not_start_a_new_line(fonts: FontLibrary) -> None:
    """Висячий пробел в конце строки места не занимает — LLM часто оставляет его в тексте."""
    lines, width, _ = measure("ааа ббб ", box_for_chars(7), fonts)
    assert lines == 1
    assert width == 7 * CHAR_EMU


def test_double_space_at_a_break_does_not_add_an_empty_line(fonts: FontLibrary) -> None:
    assert measure("ааа  ббб", box_for_chars(3), fonts)[0] == 2


def test_double_space_inside_a_line_takes_width(fonts: FontLibrary) -> None:
    assert measure("а  б", box_for_chars(10), fonts)[1] == 4 * CHAR_EMU


def test_long_word_after_a_partly_filled_line_starts_a_new_line(fonts: FontLibrary) -> None:
    assert measure("аа " + "б" * 15, box_for_chars(10), fonts)[0] == 3


def test_missing_glyph_is_not_measured_narrower_than_a_letter(tmp_path: Path) -> None:
    """Знака нет в шрифте — рендер возьмёт его из другого, и ширина будет настоящей."""
    make_font(tmp_path, "Deck Sans", advance=500, notdef_advance=100)
    fonts = FontLibrary([tmp_path])
    box = box_for_chars(10)
    letters = measure_text("ааа", font_family="Deck Sans", size_pt=SIZE_PT, box=box, fonts=fonts)
    missing = measure_text("₽₽₽", font_family="Deck Sans", size_pt=SIZE_PT, box=box, fonts=fonts)
    assert missing.width_emu >= letters.width_emu


def test_empty_text_takes_no_space(fonts: FontLibrary) -> None:
    assert measure("", box_for_chars(10), fonts) == (0, 0, 0)


def test_height_is_lines_times_format_line_pitch(fonts: FontLibrary) -> None:
    """Шаг строки 1,2 кегля: так верстают и PowerPoint, и LibreOffice, независимо от гарнитуры."""
    _, _, height = measure("а\nб\nв", box_for_chars(10), fonts)
    assert height == round(3 * LINE_HEIGHT_RATIO * SIZE_PT * EMU_PER_PT)


def test_line_spacing_scales_height(fonts: FontLibrary) -> None:
    single = measure("а\nб", box_for_chars(10), fonts)[2]
    double = measure("а\nб", box_for_chars(10), fonts, line_spacing=2.0)[2]
    assert double == 2 * single


def test_wider_font_wraps_earlier(tmp_path: Path) -> None:
    make_font(tmp_path, "Narrow", advance=400)
    make_font(tmp_path, "Wide", advance=600)
    fonts = FontLibrary([tmp_path])
    text = "слово " * 20
    box = box_for_chars(30)
    narrow = measure_text(text, font_family="Narrow", size_pt=SIZE_PT, box=box, fonts=fonts)
    wide = measure_text(text, font_family="Wide", size_pt=SIZE_PT, box=box, fonts=fonts)
    assert wide.lines > narrow.lines


def test_result_reports_whether_the_template_font_was_used(fonts: FontLibrary) -> None:
    exact = measure_text("а", font_family="Deck Sans", size_pt=SIZE_PT, box=box_for_chars(5),
                         fonts=fonts)
    guessed = measure_text("а", font_family="Нет такого", size_pt=SIZE_PT,
                           box=box_for_chars(5), fonts=fonts)
    assert exact.font_exact
    assert not guessed.font_exact
