"""Общие фикстуры. Синтетический манифест — единственный «шаблон», который знает код тестов.

Он специально непохож на шаблоны организаторов: если тест зелёный только на них,
значит проверяется не то (C6).
"""

from __future__ import annotations

import pytest

from deckforge.domain.enums import ColorRef, FontRef, LayoutKind, TextRole
from deckforge.domain.template import (
    Grid,
    LayoutCapacity,
    LayoutSpec,
    Margins,
    PlaceholderSpec,
    SlideSize,
    TemplateManifest,
    Theme,
    ThemeColors,
    ThemeFonts,
    TypographyStep,
)

EMU_PER_CM = 360_000


@pytest.fixture
def theme() -> Theme:
    return Theme(
        colors=ThemeColors(
            dk1="#101014",
            lt1="#FFFFFF",
            dk2="#3C4250",
            lt2="#EEF1F6",
            accent1="#2E6BE6",
            accent2="#12B886",
            accent3="#F59F00",
            accent4="#E03131",
            accent5="#7048E8",
            accent6="#0CA678",
            hlink="#1C7ED6",
            folHlink="#9775FA",
        ),
        fonts=ThemeFonts(major_latin="TestSans Display", minor_latin="TestSans Text"),
    )


@pytest.fixture
def manifest(theme: Theme) -> TemplateManifest:
    slide = SlideSize(cx_emu=33 * EMU_PER_CM + 866_000, cy_emu=19 * EMU_PER_CM, aspect="16:9")
    margins = Margins(
        left=2 * EMU_PER_CM, right=2 * EMU_PER_CM, top=EMU_PER_CM, bottom=EMU_PER_CM
    )
    body = PlaceholderSpec(
        idx=1,
        ph_type="BODY",
        role=TextRole.BODY,
        x=margins.left,
        y=5 * EMU_PER_CM,
        cx=slide.cx_emu - margins.left - margins.right,
        cy=11 * EMU_PER_CM,
    )
    title = PlaceholderSpec(
        idx=0,
        ph_type="TITLE",
        role=TextRole.TITLE,
        x=margins.left,
        y=margins.top,
        cx=slide.cx_emu - margins.left - margins.right,
        cy=3 * EMU_PER_CM,
    )
    return TemplateManifest(
        template_id="sha256:" + "0" * 64,
        source_name="synthetic.pptx",
        slide_size=slide,
        theme=theme,
        typography_scale=[
            TypographyStep(
                role=TextRole.TITLE,
                size_pt=40,
                font_ref=FontRef.MAJOR_LATIN,
                bold=True,
                color_ref=ColorRef.DK1,
            ),
            TypographyStep(
                role=TextRole.SUBTITLE,
                size_pt=24,
                font_ref=FontRef.MINOR_LATIN,
                color_ref=ColorRef.DK2,
            ),
            TypographyStep(
                role=TextRole.BODY,
                size_pt=18,
                font_ref=FontRef.MINOR_LATIN,
                color_ref=ColorRef.DK1,
            ),
            TypographyStep(
                role=TextRole.CAPTION,
                size_pt=12,
                font_ref=FontRef.MINOR_LATIN,
                color_ref=ColorRef.DK2,
            ),
        ],
        grid=Grid(margins_emu=margins, columns=12, gutter_emu=EMU_PER_CM // 2),
        layouts=[
            LayoutSpec(
                layout_id="L01",
                name="Титул",
                master="M01",
                index=0,
                kind=LayoutKind.TITLE,
                kind_confidence=0.95,
                kind_source="heuristic",
                capacity=LayoutCapacity(max_bullets=0, max_chars_body=0, max_chars_title=90),
                placeholders=[title],
            ),
            LayoutSpec(
                layout_id="L07",
                name="Заголовок и содержимое",
                master="M01",
                index=1,
                kind=LayoutKind.BULLETS,
                kind_confidence=0.86,
                kind_source="vlm+heuristic",
                capacity=LayoutCapacity(
                    max_bullets=6,
                    max_chars_body=420,
                    max_chars_title=90,
                    supports_chart=True,
                    supports_table=True,
                ),
                placeholders=[title, body],
            ),
        ],
        parser_version="1.0.0",
    )
