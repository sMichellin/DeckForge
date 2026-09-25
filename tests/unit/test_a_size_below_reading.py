"""Кегль ниже порога читаемости — не вписывание. Change `a-size-below-reading-is-not-a-fit` (RG35).

Прогон `b937ec5` после RG29: WorkSpace s03 — тело 9,1 pt, VK Tech s07 — 7,8 pt при пороге 10 pt
(`scripts/check_deck_readable.py`). Предел спуска зоны считается в ступенях (`_ZONE_STEPS_DOWN`),
а нижние ступени шкал достроены парсером (`12 · 0,65 = 7,8`), и две ступени до них доходят.

Шрифт синтетический: каждый знак, пробел тоже, шириной 0,6 кегля; строка — 1,2 кегля; поля
рамки — 91 440 EMU по бокам и 45 720 сверху и снизу. Шкала — синтетическая 40 / 24 / 18 / 12
(`tests/conftest.py`) плюс достроенная ступень 7,8, как у шаблонов кейса.

Рамка 3 000 000 × 365 760 EMU: строка шириной 2 817 120 EMU = 221,8 pt, высота 274 320 EMU =
21,6 pt. Фраза `TEXT` (31 знак): при 18 pt (10,8 pt на знак) — две строки по 43,2 pt, не влезает;
при 12 pt (7,2 pt на знак, 223,2 pt) — две строки по 14,4 pt, 28,8 pt, не влезает; при 7,8 pt
(145,1 pt) — одна строка 9,36 pt, влезает. Ступени 18 → 12 → 7,8 — это ровно две ступени.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import ColorRef, FontRef, TextRole
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest, TypographyStep
from deckforge.layout.by_design import DesignRules
from deckforge.layout.fitting import fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.nodes.fit import _fit_shortening
from tests.unit.test_layout_fonts import make_font

CONTENT = ContentPackage(brief=Brief(purpose="report", audience="правление", target_slides=5))
TEXT = "Выручка выросла на треть за год"
BOX_CX, BOX_CY = 3_000_000, 365_760
#: Ступень, которую парсер достраивает под шкалой шаблона (12 · 0,65).
LOW_STEP = 7.8


@pytest.fixture
def low(manifest: TemplateManifest) -> TemplateManifest:
    """Синтетический шаблон со ступенью ниже порога, как у шаблонов кейса."""
    extra = TypographyStep(
        role=TextRole.CAPTION, size_pt=LOW_STEP, font_ref=FontRef.MINOR_LATIN,
        color_ref=ColorRef.DK2,
    )
    return manifest.model_copy(
        update={"typography_scale": [*manifest.typography_scale, extra]}
    )


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=600, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=600)
    return FontLibrary([tmp_path])


def zone(size_pt: float, cx: int = BOX_CX, cy: int = BOX_CY) -> Zone:
    return Zone(
        zone_id="z383", xml_id=383, role=TypeLevel.BODY, capacity_chars=60,
        size_pt=size_pt, x=914_400, y=914_400, cx=cx, cy=cy,
    )


def rules(manifest: TemplateManifest, z: Zone, **floor: float) -> DesignRules:
    recipe = Recipe(recipe_id="ex001", example_index=1, kind=RecipeKind.TEXT, zones=[z])
    ds = derive(manifest).model_copy(update={"recipes": [recipe]})
    return DesignRules(manifest, ds, **floor)


def by_recipe(text: str) -> SlideIR:
    return SlideIR(
        slide_id="s03", layout_id="нет-такого-макета", variant="A", recipe_id="ex001",
        blocks=[TextBlock(block_id="p0", role=TextRole.BODY, text=text, zone_id="z383")],
    )


def test_a_step_below_reading_is_not_taken_the_text_is_shortened_with_a_note(
    low: TemplateManifest, fonts: FontLibrary
) -> None:
    """Сценарий «Следующая ступень ниже порога»: на 18 и 12 pt не влезает, 7,8 pt — ниже
    порога 10 pt. Кегль остаётся 12 pt, текст сокращается, заметка называет сокращение."""
    fitted, notes = _fit_shortening(by_recipe(TEXT), low, fonts, CONTENT, rules(low, zone(18)))

    fit = fitted.fit_report["p0"]
    assert fit.final_size_pt == 12
    assert fit.overflow is False
    assert fitted.blocks[0].text != TEXT
    assert any(note.startswith("s03/p0: текст сокращён") for note in notes)


def test_a_block_that_fits_above_reading_keeps_its_outcome(
    low: TemplateManifest, fonts: FontLibrary
) -> None:
    """Сценарий «Влезает на ступени не ниже порога»: «Выручка выросла на треть» (24 знака)
    при 18 pt — 259,2 pt, две строки, не влезает; при 12 pt — 172,8 pt, одна строка 14,4 pt,
    влезает. Исход прежний: 12 pt, ступень вниз, текст цел, заметок нет."""
    text = "Выручка выросла на треть"
    fitted, notes = _fit_shortening(by_recipe(text), low, fonts, CONTENT, rules(low, zone(18)))

    fit = fitted.fit_report["p0"]
    assert (fit.final_size_pt, fit.strategy, fit.overflow) == (12, "shrink", False)
    assert fitted.blocks[0].text == text
    assert notes == []


#: Рамка ровно в одну строку 9 pt: 10,8 pt = 137 160 EMU плюс поля 91 440 — не якорь (D02).
AUTHOR_CY = 228_600


@pytest.mark.parametrize(
    ("text", "shortened"),
    [
        # 7 знаков при 9 pt (5,4 pt на знак) — 37,8 pt, одна строка: как у автора.
        ("Выручка", False),
        # 47 знаков при 9 pt — 253,8 pt, две строки, не влезают; при 7,8 pt — 220 pt, одна
        # строка: прежде кегль уходил на ступень 7,8 — ниже и порога, и кегля автора.
        ("Выручка выросла на треть за год и полгода тоже", True),
    ],
)
def test_an_author_size_below_reading_is_neither_raised_nor_lowered(
    low: TemplateManifest, fonts: FontLibrary, text: str, shortened: bool
) -> None:
    """Кегль автора зоны 9 pt ниже порога: не поднимается; влезает — `as_is`, не влезает —
    сокращение на кегле автора, не ниже."""
    design = rules(low, zone(9, cy=AUTHOR_CY))
    fitted, notes = _fit_shortening(by_recipe(text), low, fonts, CONTENT, design)

    fit = fitted.fit_report["p0"]
    assert fit.final_size_pt == 9
    assert fit.overflow is False
    assert (fitted.blocks[0].text != text) is shortened
    assert any(note.startswith("s03/p0: текст сокращён") for note in notes) is shortened
    if not shortened:
        assert fit.strategy == "as_is"


def test_the_reading_floor_is_a_parameter(low: TemplateManifest, fonts: FontLibrary) -> None:
    """Тот же блок, что в первом сценарии, при пороге 7 pt: ступень 7,8 pt разрешена —
    текст цел на 7,8 pt, сокращения нет."""
    design = rules(low, zone(18), reading_floor_pt=7)
    fitted, notes = _fit_shortening(by_recipe(TEXT), low, fonts, CONTENT, design)

    fit = fitted.fit_report["p0"]
    assert (fit.final_size_pt, fit.strategy) == (LOW_STEP, "shrink")
    assert fitted.blocks[0].text == TEXT
    assert notes == []


def test_a_placeholder_block_does_not_go_below_reading_either(
    low: TemplateManifest, fonts: FontLibrary
) -> None:
    """Блок вне рецепта (свои координаты, макет `L07`) спускается по всей шкале: 18 → 12 → 7,8.
    Ступень 7,8 pt ниже порога не берётся — стратегия сокращения на 12 pt."""
    block = TextBlock(
        block_id="p0", role=TextRole.BODY, text=TEXT, x=914_400, y=914_400, cx=BOX_CX, cy=BOX_CY
    )
    slide = SlideIR(slide_id="s03", layout_id="L07", variant="A", blocks=[block])

    fitted = fit_slide(slide, low, fonts=fonts)

    fit = fitted.fit_report["p0"]
    assert (fit.final_size_pt, fit.overflow, fit.strategy) == (12, True, "shorten")
