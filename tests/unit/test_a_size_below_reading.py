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
from deckforge.domain.base import BBox
from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import ColorRef, FontRef, ListStyle, SmartArtPattern, TextRole
from deckforge.domain.slide import (
    BulletItem,
    BulletsBlock,
    QuoteBlock,
    SlideIR,
    SmartArtBlock,
    TableBlock,
    TextBlock,
)
from deckforge.domain.template import TemplateManifest, TypographyStep
from deckforge.layout.by_design import DesignRules
from deckforge.layout.fitting import (
    fit_boxed,
    fit_icon_list,
    fit_slide,
    fit_smartart,
    fit_table,
)
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


# --- Остальные пути спуска кегля: тот же пол, свой исход переполнения ------------------------
#
# Одна строка текста «Выручка» по высоте: при 18 pt — 274 320 EMU, при 12 pt — 182 880, при 7,8 pt —
# 118 872 (1,2 кегля · 12 700). Поля рамки сверху и снизу — 91 440 EMU. Рамка высотой 241 440 EMU
# держит строку 7,8 pt (210 312 с полями) и не держит строку 12 pt (274 320 с полями): прежде кегль
# уходил на 7,8 pt, теперь стоит на 12 pt — наименьшей ступени не ниже порога — с переполнением.
ONE_LINE_AT_LOW = 241_440
ONE_LINE_AT_18 = 365_760
WIDE = 6_000_000


def icon_list() -> BulletsBlock:
    return BulletsBlock(
        block_id="b", items=[BulletItem(text="Выручка", icon="chart-line")],
        style=ListStyle.ICON, x=0, y=0, cx=WIDE, cy=ONE_LINE_AT_LOW,
    )


@pytest.mark.parametrize(
    ("cy", "expected"),
    [(ONE_LINE_AT_18, (18, False, "as_is")), (ONE_LINE_AT_LOW, (12, True, "shorten"))],
)
def test_an_icon_list_does_not_go_below_reading(
    low: TemplateManifest, fonts: FontLibrary, cy: int, expected: tuple[float, bool, str]
) -> None:
    """Иконочный список: влезает на 18 pt — исход прежний; строка встаёт только на 7,8 pt —
    12 pt и сокращение (узел `fit` сокращает пункты и отбрасывает хвост)."""
    block = icon_list().model_copy(update={"cy": cy})
    fit = fit_icon_list(block, block.bbox, low, DesignRules(low), fonts=fonts)  # type: ignore[arg-type]

    assert (fit.final_size_pt, fit.overflow, fit.strategy) == expected


@pytest.mark.parametrize(
    ("cy", "expected"),
    [(ONE_LINE_AT_18, (18, False, "as_is")), (ONE_LINE_AT_LOW, (12, True, "shorten"))],
)
def test_a_table_does_not_go_below_reading(
    low: TemplateManifest, fonts: FontLibrary, cy: int, expected: tuple[float, bool, str]
) -> None:
    """Таблица в одну ячейку: строка таблицы — строка текста плюс поля 91 440 EMU, меряется
    против полной высоты рамки. Не влезла на пороге — переполнение: писатель пишет её
    буллетами («таблица → буллеты (не влезла)»), а буллеты держат тот же порог."""
    block = TableBlock(block_id="t", rows=[["Выручка"]], first_row_header=False)
    fit = fit_table(block, BBox(x=0, y=0, cx=WIDE, cy=cy), low, fonts=fonts)

    assert (fit.final_size_pt, fit.overflow, fit.strategy) == expected


@pytest.mark.parametrize(
    ("cy", "expected"), [(470_000, (24, False, "as_is")), (250_000, (12, True, "shorten"))]
)
def test_a_quote_does_not_go_below_reading(
    low: TemplateManifest, fonts: FontLibrary, cy: int, expected: tuple[float, bool, str]
) -> None:
    """Цитата стартует с 24 pt (ступень дизайн-системы). Рамка 250 000 EMU (за вычетом
    отбивок) держит строку 7,8 pt и не держит строку 12 pt — теперь 12 pt и сокращение
    (узел `fit` сокращает цитату, не влезла и так — снимает с заметкой)."""
    block = QuoteBlock(block_id="q", text="Выручка выросла")
    fit = fit_boxed(block, BBox(x=0, y=0, cx=WIDE, cy=cy), low, DesignRules(low), fonts=fonts)

    assert (fit.final_size_pt, fit.overflow, fit.strategy) == expected


@pytest.mark.parametrize(
    ("cy", "expected"), [(500_000, (18, False, "as_is")), (300_000, (12, True, "shorten"))]
)
def test_a_diagram_does_not_go_below_reading(
    low: TemplateManifest, fonts: FontLibrary, cy: int, expected: tuple[float, bool, str]
) -> None:
    """Схема из трёх шагов в полосе 8 000 000 EMU: при высоте 300 000 подписи встают только
    на 7,8 pt. Теперь 12 pt и переполнение — узел `fit` пишет схему списком тех же пунктов."""
    block = SmartArtBlock(
        block_id="s", pattern=SmartArtPattern.PROCESS, items=["Сбор", "Анализ", "Отчёт"]
    )
    box = BBox(x=0, y=0, cx=8_000_000, cy=cy)
    fit = fit_smartart(block, box, low, fonts=fonts, design=DesignRules(low))

    assert (fit.final_size_pt, fit.overflow, fit.strategy) == expected


# --- D06: порог не снимает текст, который иначе встал бы ------------------------------------
#
# Зона 627 380 EMU шириной: строка 444 500 EMU = 35 pt. «Анализ» (6 знаков, полужирная мерка) —
# 64,8 pt при 18, 43,2 pt при 12, 28,08 pt при 7,8: встаёт только на ступени ниже порога.
# Сокращать одно слово некуда — на пороге блок был бы снят целиком (VK WorkSpace s08, ex008).
NARROW_CX = 627_380
BELOW_READING = "below_reading"


def test_a_block_that_shortening_would_empty_stays_below_reading(
    low: TemplateManifest, fonts: FontLibrary
) -> None:
    """Ни одно слово не встаёт ни на одной ступени не ниже порога — блок остаётся на
    наибольшей ступени под порогом, где встаёт (7,8 pt, в пределах двух ступеней), текст цел,
    и вписывание помечает это стратегией `below_reading` (для заметки в узле `fit`)."""
    design = rules(low, zone(18, cx=NARROW_CX))
    fitted, _ = _fit_shortening(by_recipe("Анализ"), low, fonts, CONTENT, design)

    fit = fitted.fit_report["p0"]
    assert (fit.final_size_pt, fit.overflow, fit.strategy) == (LOW_STEP, False, BELOW_READING)
    assert [block.text for block in fitted.blocks] == ["Анализ"]  # type: ignore[union-attr]


def test_an_explicit_size_snapped_below_reading_is_checked(
    low: TemplateManifest, fonts: FontLibrary
) -> None:
    """Явный кегль 11 pt вне шкалы привязывается к 7,8 pt — это ступень ниже порога, и она
    проходит ту же проверку: ступеней не ниже порога у блока нет, сокращение оставило бы
    ноль — ступень под порогом берётся по правилу D06 и помечается, а не молча."""
    block = TextBlock(
        block_id="p0", role=TextRole.BODY, text="Выручка", size_pt=11,
        x=914_400, y=914_400, cx=WIDE, cy=ONE_LINE_AT_18,
    )
    slide = SlideIR(slide_id="s03", layout_id="L07", variant="A", blocks=[block])

    fit = fit_slide(slide, low, fonts=fonts).fit_report["p0"]

    assert (fit.final_size_pt, fit.strategy) == (LOW_STEP, BELOW_READING)


def test_the_floor_is_the_greater_of_reading_and_the_title_floor(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Шкала 40 / 9,1 / 7,8, тело 7,8: пол заголовка — ближайшая ступень крупнее тела, 9,1 pt,
    ниже порога. Полоса 701 040 EMU держит строку 40 pt (609 600 + поля). «Выручка выросла на
    треть за год» (31 знак) при 40 pt — 744 pt, в строке 458 pt: две строки, не влезает; при 9,1 —
    одна. Пол — наибольшее из 10 и 9,1: ступень 9,1 не берётся, заголовок сокращается на 40 pt."""
    scale = [
        TypographyStep(role=TextRole.TITLE, size_pt=40, font_ref=FontRef.MAJOR_LATIN,
                       bold=True, color_ref=ColorRef.DK1),
        TypographyStep(role=TextRole.SUBTITLE, size_pt=9.1, font_ref=FontRef.MINOR_LATIN,
                       color_ref=ColorRef.DK2),
        TypographyStep(role=TextRole.BODY, size_pt=LOW_STEP, font_ref=FontRef.MINOR_LATIN,
                       color_ref=ColorRef.DK1),
    ]
    small = manifest.model_copy(update={"typography_scale": scale})
    title = TextBlock(
        block_id="t", role=TextRole.TITLE, text=TEXT, x=914_400, y=914_400, cx=WIDE, cy=701_040
    )
    slide = SlideIR(slide_id="s03", layout_id="L07", variant="A", blocks=[title])

    fit = fit_slide(slide, small, fonts=fonts).fit_report["t"]

    assert (fit.final_size_pt, fit.overflow, fit.strategy) == (40, True, "shorten")
