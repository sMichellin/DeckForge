"""Вписывание не пропускает слайд по рецепту. Change `fitting-does-not-skip-the-recipe` (RG29).

Прогоны 24.09 (VK WorkSpace, VK Tech, VK Education): все слайды по рецепту, а узел `fit`
возвращал такой слайд нетронутым. На превью — «извлечен / ие» в рамке 3 879 511 EMU
при 54 pt и титул 144 pt в рамке высотой 1 876 890 EMU за краями слайда.

Шрифт синтетический: каждый знак, пробел тоже, шириной 0,6 кегля. Поэтому ожидания
считаются вручную: слово из `n` знаков при кегле `s` занимает `n · 0,6 · s · 12 700` EMU,
строка — `1,2 · s · 12 700` EMU, поля рамки — 91 440 EMU по бокам и 45 720 сверху и снизу.
Шкала синтетического шаблона — 40 / 24 / 18 / 12 (`tests/conftest.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.base import BBox
from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.domain.template import (
    ExampleShape,
    ShapeKind,
    TemplateExample,
    TemplateManifest,
)
from deckforge.layout.by_design import DesignRules
from deckforge.layout.fitting import AS_IS, SHRINK, fit_slide, fit_text
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.nodes.fit import _fit_shortening
from tests.unit.test_layout_fonts import make_font

CONTENT = ContentPackage(brief=Brief(purpose="report", audience="правление", target_slides=5))

#: Рамки фигур из `deck.pptx` прогона d541b632ff97 (VK WorkSpace): s05 `720;p34` и титул
#: s01 `874;p44`. Числа шаблона живут только в тестах (правило 2).
WORD_CX, WORD_CY = 3_879_511, 3_166_268
TITLE_CX, TITLE_CY = 7_827_335, 1_876_890


def zone(zone_id: str, size_pt: float | None, cx: int | None, cy: int | None) -> Zone:
    framed = cx is not None
    return Zone(
        zone_id=zone_id, xml_id=int(zone_id[1:]), role=TypeLevel.BODY, capacity_chars=30,
        size_pt=size_pt, x=914_400 if framed else None, y=914_400 if framed else None,
        cx=cx, cy=cy,
    )


def rules(manifest: TemplateManifest, *zones: Zone) -> DesignRules:
    recipe = Recipe(recipe_id="ex018", example_index=18, kind=RecipeKind.TEXT, zones=list(zones))
    ds = derive(manifest).model_copy(update={"recipes": [recipe]})
    return DesignRules(manifest, ds)


def by_recipe(*blocks: TextBlock, layout_id: str = "L07") -> SlideIR:
    return SlideIR(
        slide_id="s05", layout_id=layout_id, variant="A", recipe_id="ex018", blocks=list(blocks)
    )


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=600, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=600)
    return FontLibrary([tmp_path])


def test_a_word_wider_than_the_box_does_not_fit(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Площади хватает, а слово шире строки — кегль не вмещается (любой блок, не только зона).

    «извлечение» при 40 pt: 10 · 0,6 · 40 · 12 700 = 3 048 000 EMU, строка рамки —
    3 000 000 − 182 880 = 2 817 120. По знакам слово встало бы в две строки
    (1 219 200 EMU при высоте 3 074 828) — прежде это считалось «влезло».
    При 24 pt — 1 828 800 EMU: слово целиком в строке.
    """
    box = BBox(x=0, y=0, cx=3_000_000, cy=3_166_268)

    fit = fit_text(
        "извлечение", box=box, manifest=manifest, start_size_pt=40,
        font_family=manifest.theme.fonts.minor_latin, fonts=fonts,
    )

    assert fit.overflow is False
    assert fit.final_size_pt == 24
    assert fit.strategy == SHRINK


def test_a_word_that_fits_keeps_the_size(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    box = BBox(x=0, y=0, cx=6_000_000, cy=3_166_268)

    fit = fit_text(
        "извлечение", box=box, manifest=manifest, start_size_pt=40,
        font_family=manifest.theme.fonts.minor_latin, fonts=fonts,
    )

    assert (fit.final_size_pt, fit.strategy, fit.overflow) == (40, AS_IS, False)


def test_a_word_wider_than_its_zone_steps_the_size_down(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """«извлечение» при 54 pt: 10 · 0,6 · 54 · 12 700 = 4 114 800 EMU, строка зоны —
    3 879 511 − 182 880 = 3 696 631. Ступень ниже 54 на шкале — 40: 3 048 000 EMU."""
    design = rules(manifest, zone("z720", 54, WORD_CX, WORD_CY))
    slide = by_recipe(
        TextBlock(block_id="b1", role=TextRole.BODY, text="извлечение", zone_id="z720")
    )

    fit = fit_slide(slide, manifest, fonts=fonts, content=CONTENT, design=design).fit_report["b1"]

    assert fit.overflow is False
    assert fit.final_size_pt == 40
    assert 10 * 0.6 * fit.final_size_pt * 12_700 < WORD_CX - 182_880


def test_the_same_word_in_a_twice_wider_zone_keeps_the_zone_size(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Кегль зоны 54 вне шкалы 40 / 24 / 18 / 12 — и всё равно старт: это кегль автора."""
    design = rules(manifest, zone("z720", 54, 2 * WORD_CX, WORD_CY))
    slide = by_recipe(
        TextBlock(block_id="b1", role=TextRole.BODY, text="извлечение", zone_id="z720")
    )

    fit = fit_slide(slide, manifest, fonts=fonts, content=CONTENT, design=design).fit_report["b1"]

    assert (fit.final_size_pt, fit.strategy, fit.overflow) == (54, AS_IS, False)


def test_every_text_block_in_a_framed_zone_gets_a_record_and_frames_stay(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Сценарий «Зона несёт рамку»: запись на каждый текстовый блок, рамки не тронуты."""
    zones = (zone("z718", 36, TITLE_CX, 1_167_572), zone("z720", 54, WORD_CX, WORD_CY))
    design = rules(manifest, *zones)
    slide = by_recipe(
        TextBlock(block_id="t", role=TextRole.TITLE, text="Автоматическая генерация",
                  zone_id="z718"),
        TextBlock(block_id="b1", role=TextRole.BODY, text="Анализ шаблона, извлечение",
                  zone_id="z720"),
        layout_id="нет-такого-макета",
    )

    fitted = fit_slide(slide, manifest, fonts=fonts, content=CONTENT, design=design)

    assert set(fitted.fit_report) == {"t", "b1"}
    assert design.ds.recipes[0].zones == list(zones)
    assert all(block.bbox is None for block in fitted.blocks)


def test_a_zone_without_a_frame_is_skipped(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    """Сценарий «Зона рамки не несёт»: каталог до RG18 — записи нет, прогон не падает."""
    design = rules(manifest, zone("z720", 54, None, None))
    slide = by_recipe(
        TextBlock(block_id="b1", role=TextRole.BODY, text="извлечение", zone_id="z720"),
        layout_id="нет-такого-макета",
    )

    assert fit_slide(slide, manifest, fonts=fonts, content=CONTENT, design=design).fit_report == {}


TITLE_TEXT = "AI-генерация презентаций в фирменном стиле"


def test_a_long_cover_title_yields_its_size_and_stays_whole(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Титул s01: 42 знака в зоне 7 827 335 × 1 876 890 EMU при 144 pt.

    При 144 pt слово «презентаций» — 11 · 0,6 · 144 · 12 700 = 12 070 080 EMU при строке
    7 644 455, да и одна строка (2 194 560 EMU) выше рамки (1 785 450). При 40 pt знак —
    24 pt, в строке 601,9 pt: «AI-генерация презентаций» (576 pt) / «в фирменном стиле» —
    две строки, 1 219 200 EMU. Узел `fit` целиком: заголовок не режется, кегль уступает.
    """
    design = rules(manifest, zone("z874", 144, TITLE_CX, TITLE_CY))
    slide = by_recipe(
        TextBlock(block_id="t", role=TextRole.TITLE, text=TITLE_TEXT, zone_id="z874"),
        layout_id="нет-такого-макета",
    )

    fitted, _ = _fit_shortening(slide, manifest, fonts, CONTENT, design)

    fit = fitted.fit_report["t"]
    assert fit.overflow is False
    assert fit.final_size_pt == 40
    assert fitted.blocks[0].text == TITLE_TEXT




def test_a_word_one_step_down_keeps_the_text_whole(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Сценарий «Текст вмещается ступенью ниже»: 54 → 40, текст цел, сокращений нет."""
    design = rules(manifest, zone("z720", 54, WORD_CX, WORD_CY))
    text = "Анализ шаблона, извлечение"
    slide = by_recipe(TextBlock(block_id="b1", role=TextRole.BODY, text=text, zone_id="z720"))

    fitted, notes = _fit_shortening(slide, manifest, fonts, CONTENT, design)

    assert fitted.fit_report["b1"].final_size_pt == 40
    assert fitted.blocks[0].text == text
    assert notes == []


def test_text_that_fits_no_step_is_shortened_with_a_note(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Сценарий «Текст не вмещается и после спуска»: сокращение последним, с заметкой.

    Рамка 3 000 000 × 274 320 EMU: одна строка 12 pt (182 880 EMU) шириной 221,8 pt.
    31 знак при 12 pt — 223,2 pt: две строки ни на одной ступени.
    """
    design = rules(manifest, zone("z720", 18, 3_000_000, 274_320))
    text = "Выручка выросла на треть за год"
    slide = by_recipe(TextBlock(block_id="b1", role=TextRole.BODY, text=text, zone_id="z720"))

    fitted, notes = _fit_shortening(slide, manifest, fonts, CONTENT, design)

    assert fitted.fit_report["b1"].overflow is False
    assert fitted.blocks[0].text != text
    assert any(note.startswith("s05/b1: текст сокращён") for note in notes)


def test_a_word_wider_than_every_step_shortens_the_text_with_a_note(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Сценарий «Ступени шкалы исчерпаны»: «извлечение» при 12 pt — 72 pt, строка
    рамки шириной 1 000 000 EMU — 64,3 pt. Шире на всех ступенях — текст сокращается."""
    design = rules(manifest, zone("z720", 18, 1_000_000, WORD_CY))
    text = "Анализ шаблона извлечение данных"
    slide = by_recipe(TextBlock(block_id="b1", role=TextRole.BODY, text=text, zone_id="z720"))

    fitted, notes = _fit_shortening(slide, manifest, fonts, CONTENT, design)

    assert "извлечение" not in fitted.blocks[0].text
    assert fitted.fit_report["b1"].overflow is False
    assert any(note.startswith("s05/b1: текст сокращён") for note in notes)


def test_a_narrow_zone_gives_whole_words_not_letters(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Правило 10: на холодном шаблоне `cb04bb47fc47` зоны узкие, `capacity_chars` = 2.

    Рамка шириной 1 000 000 EMU — строка 64,3 pt: при кегле зоны 54 pt (знак 32,4 pt)
    в неё встаёт один знак, и без вписывания «выручки» шло бы по букве в строку.
    Спуск по шкале: «выручки» — 168 / 100,8 / 75,6 pt на 40 / 24 / 18, на 12 pt — 50,4 pt.
    """
    design = rules(manifest, zone("z720", 54, 1_000_000, WORD_CY))
    text = "Рост выручки"
    slide = by_recipe(TextBlock(block_id="b1", role=TextRole.BODY, text=text, zone_id="z720"))

    fitted, notes = _fit_shortening(slide, manifest, fonts, CONTENT, design)

    fit = fitted.fit_report["b1"]
    assert (fit.final_size_pt, fit.overflow, fit.lines) == (12, False, 2)
    assert fitted.blocks[0].text == text
    assert notes == []


# --- D01 (§10): зона меряется тем, что о ней известно ---------------------------------


def with_example_font(manifest: TemplateManifest, xml_id: int, family: str) -> TemplateManifest:
    """Манифест, у которого фигура-пример зоны набрана своей гарнитурой."""
    shape = ExampleShape(
        shape_id=str(xml_id), kind=ShapeKind.TEXT, x=0, y=0, cx=WORD_CX, cy=WORD_CY,
        xml_id=xml_id, font_family=family,
    )
    example = TemplateExample(slide_index=18, shapes=[shape])
    return manifest.model_copy(update={"examples": [example]})


def test_a_zone_is_measured_in_the_font_of_its_example(
    tmp_path: Path, manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """§10(а): гарнитура — у фигуры-примера по `Zone.xml_id`, а не у роли.

    Рамка вдвое шире `WORD_CX`, строка 7 576 142 EMU. Гарнитурой роли (0,6 кегля)
    «извлечение» при 54 pt — 4 114 800 EMU, влезает. Гарнитурой примера (1,2 кегля) —
    8 229 600, не влезает; при 40 pt — 6 096 000, влезает.
    """
    make_font(tmp_path, "WideSans", advance=1200)
    wide = with_example_font(manifest, 720, "WideSans")
    design = rules(wide, zone("z720", 54, 2 * WORD_CX, WORD_CY))
    slide = by_recipe(
        TextBlock(block_id="b1", role=TextRole.BODY, text="извлечение", zone_id="z720")
    )

    fit = fit_slide(slide, wide, fonts=fonts, content=CONTENT, design=design).fit_report["b1"]

    assert (fit.final_size_pt, fit.overflow) == (40, False)


def test_a_zone_word_is_measured_bold(tmp_path: Path, manifest: TemplateManifest) -> None:
    """§10(б): начертание зоны неизвестно — слово меряется полужирным.

    Рамка 4 600 000 EMU, строка 4 417 120. «извлечение» при 54 pt: обычным (0,6) —
    4 114 800, влезает; полужирным (0,7) — 4 800 600, нет. При 40 pt полужирным — 3 556 000.
    """
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=600)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=700, bold=True)
    fonts = FontLibrary([tmp_path])
    design = rules(manifest, zone("z720", 54, 4_600_000, WORD_CY))
    slide = by_recipe(
        TextBlock(block_id="b1", role=TextRole.BODY, text="извлечение", zone_id="z720")
    )

    fit = fit_slide(slide, manifest, fonts=fonts, content=CONTENT, design=design).fit_report["b1"]

    assert (fit.final_size_pt, fit.overflow) == (40, False)


def test_a_short_title_keeps_144_pt_in_the_real_cover_frame(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """§10(в): строку кегля 144 в титульную рамку поставил автор шаблона.

    По модели строка 144 pt — 2 194 560 EMU при месте 1 785 450: по высоте «не влезает».
    Но «Итоги» на собственном кегле зоны — одна строка по ширине (432 pt из 601,9),
    и высота тогда не проверяется.
    """
    design = rules(manifest, zone("z874", 144, TITLE_CX, TITLE_CY))
    slide = by_recipe(
        TextBlock(block_id="t", role=TextRole.TITLE, text="Итоги", zone_id="z874"),
        layout_id="нет-такого-макета",
    )

    fitted, notes = _fit_shortening(slide, manifest, fonts, CONTENT, design)

    assert (fitted.fit_report["t"].final_size_pt, fitted.fit_report["t"].strategy) == (144, AS_IS)
    assert notes == []


def test_a_one_line_title_keeps_its_size_in_a_frame_of_one_line(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """§10(в): заголовки ex005/ex010 VK WorkSpace — 36 pt в рамке высотой 626 869 EMU.

    Строка 36 pt по модели — 548 640 EMU при месте 535 429. «Итоги года» — 10 знаков,
    216 pt при строке 601,9 pt: одна строка, кегль автора остаётся.
    """
    design = rules(manifest, zone("z441", 36, TITLE_CX, 626_869))
    slide = by_recipe(
        TextBlock(block_id="t", role=TextRole.TITLE, text="Итоги года", zone_id="z441")
    )

    fitted, notes = _fit_shortening(slide, manifest, fonts, CONTENT, design)

    assert (fitted.fit_report["t"].final_size_pt, fitted.fit_report["t"].strategy) == (36, AS_IS)
    assert notes == []


def test_a_zone_does_not_grow(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    """Решение §3: зона 18 pt с запасом места — ровно 18 pt, `as_is` (плейсхолдер тела вырос бы)."""
    design = rules(manifest, zone("z719", 18, 5_973_441, 3_782_435))
    slide = by_recipe(TextBlock(block_id="b1", role=TextRole.BODY, text="Рост", zone_id="z719"))

    fitted, _ = _fit_shortening(slide, manifest, fonts, CONTENT, design)

    assert (fitted.fit_report["b1"].final_size_pt, fitted.fit_report["b1"].strategy) == (18, AS_IS)


# --- повторное ревью: границы правила строки автора и полужирного слова ----------------


def bold_wider(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    """Тело: обычное начертание — 0,6 кегля, полужирное — 0,7."""
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=600)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=700, bold=True)
    return FontLibrary([tmp_path])


def test_the_authors_line_holds_only_on_the_zone_size(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Строка автора — только на собственном кегле зоны; ступенью ниже высота меряется.

    Рамка 3 992 880 × 591 440: строка 300 pt, высота 500 000 EMU. «Итоги года» при 54 pt —
    324 pt, две строки; при 40 pt — 240 pt, одна, но строка 609 600 EMU выше рамки;
    при 24 pt — 365 760 EMU, встаёт.
    """
    design = rules(manifest, zone("z720", 54, 3_992_880, 591_440))
    slide = by_recipe(
        TextBlock(block_id="b1", role=TextRole.BODY, text="Итоги года", zone_id="z720")
    )

    fit = fit_slide(slide, manifest, fonts=fonts, content=CONTENT, design=design).fit_report["b1"]

    assert (fit.final_size_pt, fit.overflow) == (24, False)


def test_a_placeholder_word_is_measured_in_its_own_style(
    tmp_path: Path, manifest: TemplateManifest
) -> None:
    """Полужирным меряется только зона: у плейсхолдера и свободного блока начертание известно.

    Рамка 2 087 880 EMU, строка 150 pt. «извлечение» при 24 pt: обычным — 144 pt, влезает;
    полужирным — 168 pt, не влез бы.
    """
    fonts = bold_wider(tmp_path, manifest)
    slide = SlideIR(
        slide_id="s05", layout_id="L07", variant="A",
        blocks=[TextBlock(
            block_id="b1", role=TextRole.BODY, text="извлечение", size_pt=24,
            x=914_400, y=1_828_800, cx=2_087_880, cy=WORD_CY,
        )],
    )

    fit = fit_slide(slide, manifest, fonts=fonts, content=CONTENT).fit_report["b1"]

    assert (fit.final_size_pt, fit.strategy) == (24, AS_IS)


def test_the_authors_line_is_counted_in_bold(tmp_path: Path, manifest: TemplateManifest) -> None:
    """Строка автора считается тем же начертанием, что и слово, — полужирным.

    Рамка 4 627 880 × 791 440: строка 350 pt, высота 700 000 EMU. «Итоги года» при 54 pt:
    обычным — 324 pt, одна строка; полужирным — 378 pt, две. Строки автора нет, а одна
    строка 54 pt (822 960 EMU) выше рамки — кегль уходит на 40 (609 600 EMU).
    """
    fonts = bold_wider(tmp_path, manifest)
    design = rules(manifest, zone("z720", 54, 4_627_880, 791_440))
    slide = by_recipe(
        TextBlock(block_id="b1", role=TextRole.BODY, text="Итоги года", zone_id="z720")
    )

    fit = fit_slide(slide, manifest, fonts=fonts, content=CONTENT, design=design).fit_report["b1"]

    assert (fit.final_size_pt, fit.overflow) == (40, False)
