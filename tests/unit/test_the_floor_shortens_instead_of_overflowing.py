"""Текст на пороге читаемости не остаётся выше своей рамки. RG46, D07
(`docs/agents/tasks-26-09.md`, «## RG46»).

Находка холодного прогона VK Tech, s06: «2 строк на 10 pt — 304 800 EMU при рамке
194 310 EMU». Замер показал путь: зона подписи «Вставить фото» (10 pt, рамка держит
одну строку) считалась **якорем** (D02) — высота не ограничивает, — потому что сосед
снизу урезал её высоту до 182 305 EMU (RG39). А сосед этот перекрывает её по ширине
на 19 765 EMU — 2,3 % её ширины: волосок раскладки автора, не соседство. Вписывание
называло двустрочный текст вставшим, и он рисовался поверх соседей.

Решение D07: сосед снизу — только зона, перекрывающая по ширине не меньше доли ширины
меньшей из двух. Тогда рамка меряется целиком, строку своего кегля держит, якорем
не считается, и то, что в неё не встаёт, уходит по существующей лестнице.

Шрифт синтетический: каждый знак шириной 0,6 кегля. Шкала синтетического шаблона —
40 / 24 / 18 / 12 (`tests/conftest.py`); порог читаемости — умолчание 10 pt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.domain.units import TEXT_FRAME_INSET_Y_EMU
from deckforge.layout.by_design import DesignRules
from deckforge.layout.fitting import fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.parsing import TemplateParser
from deckforge.pipeline.nodes.fit import _fit_shortening
from tests.case_templates import case_template
from tests.unit.test_layout_fonts import make_font

CONTENT = ContentPackage(brief=Brief(purpose="report", audience="жюри", target_slides=1))

#: Геометрия находки VK Tech (числа в тестах, а не в коде — правило 2): рамка подписи
#: 285 750 EMU — полезных 194 310, строка 10 pt (152 400) встаёт, две (304 800) — нет.
#: Сосед снизу начинается на 182 305 ниже её верха и заходит на неё по ширине на 19 765.
CAPTION_CY = 285_750
NEIGHBOUR_Y = 182_305
HAIR = 19_765
#: Ширина подписи: полезных 800 000 EMU — десять знаков по 76 200 (0,6 · 10 pt) в строку.
CAPTION_CX = 982_880
WIDE = 4_288_279

TWO_LINES = "Вставить фото"  # 13 знаков — две строки
ONE_LINE = "Фото"


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=600, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=600)
    return FontLibrary([tmp_path])


def zone(zone_id: str, *, x: int, y: int, cx: int, cy: int, size_pt: float) -> Zone:
    return Zone(
        zone_id=zone_id, xml_id=int(zone_id[1:]), role=TypeLevel.BODY, capacity_chars=200,
        size_pt=size_pt, x=x, y=y, cx=cx, cy=cy,
    )


def rules(manifest: TemplateManifest, *zones: Zone) -> DesignRules:
    recipe = Recipe(recipe_id="ex004", example_index=4, kind=RecipeKind.CARDS, zones=list(zones))
    ds = derive(manifest).model_copy(update={"recipes": [recipe]})
    return DesignRules(manifest, ds)


def caption_slide(text: str) -> SlideIR:
    return SlideIR(
        slide_id="s06", layout_id="L07", variant="A", recipe_id="ex004",
        blocks=[TextBlock(block_id="p0", role=TextRole.BODY, text=text, zone_id="z433")],
    )


def caption_with_neighbour(manifest: TemplateManifest, overlap: int) -> DesignRules:
    """Подпись 10 pt и сосед снизу, заходящий на неё по ширине на `overlap` EMU."""
    caption = zone("z433", x=0, y=0, cx=CAPTION_CX, cy=CAPTION_CY, size_pt=10)
    below = zone(
        "z431", x=CAPTION_CX - overlap, y=NEIGHBOUR_Y, cx=WIDE, cy=CAPTION_CY, size_pt=12
    )
    return rules(manifest, caption, below)


# --- Путь находки: волосок перекрытия не делает рамку якорем ----------------------


def test_two_lines_at_the_floor_do_not_stay_above_a_frame_of_one(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Нарушитель: двустрочная подпись в рамке на одну строку при соседе «на волосок».

    До правки рамка считалась якорем, текст — вставшим (`as_is`, 2 строки, 304 800 EMU
    при 194 310), и в файле он лежал поверх соседей. Сократить два слова некуда —
    лестница снимает блок и называет это в `notes`.
    """
    design = caption_with_neighbour(manifest, HAIR)

    fitted, notes = _fit_shortening(caption_slide(TWO_LINES), manifest, fonts, CONTENT, design)

    assert [block.block_id for block in fitted.blocks] == []
    assert (
        f"s06/p0: текст «{TWO_LINES}» снят — не помещается в место макета даже в два слова"
        in notes
    )


def test_a_line_that_the_frame_holds_stays_whole(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Норма: строка, которую рамка держит, — исход прежний: 10 pt, текст цел, в рамке."""
    design = caption_with_neighbour(manifest, HAIR)

    fitted, notes = _fit_shortening(caption_slide(ONE_LINE), manifest, fonts, CONTENT, design)

    fit = fitted.fit_report["p0"]
    assert [block.text for block in fitted.blocks if isinstance(block, TextBlock)] == [ONE_LINE]
    assert (fit.final_size_pt, fit.overflow, fit.strategy) == (10, False, "as_is")
    assert fit.required_cy_emu <= CAPTION_CY - 2 * TEXT_FRAME_INSET_Y_EMU
    assert notes == []


# --- RG39 не сломан: настоящий сосед снизу по-прежнему урезает высоту --------------

#: Зона заголовка RG39: своей высоты — на три строки 24 pt, до соседа — на одну.
TITLE_CY, BODY_TOP, TITLE_CX = 1_200_000, 500_000, 6_000_000
#: 40 знаков: при 24 pt — две строки в ширину зоны, при 18 pt — одна.
FORTY = "Ручная адаптация шаблонов замедляет ритм"


def title_size(manifest: TemplateManifest, fonts: FontLibrary, overlap: int) -> float:
    """Кегль заголовка, под которым сосед шириной 2 000 000 заходит на него на `overlap`."""
    head = zone("z1", x=0, y=0, cx=TITLE_CX, cy=TITLE_CY, size_pt=24)
    body = zone(
        "z2", x=TITLE_CX - overlap, y=BODY_TOP, cx=2_000_000, cy=1_000_000, size_pt=24
    )
    slide = SlideIR(
        slide_id="s05", layout_id="L07", variant="A", recipe_id="ex004",
        blocks=[TextBlock(block_id="b1", role=TextRole.TITLE, text=FORTY, zone_id="z1")],
    )
    result = fit_slide(slide, manifest, fonts=fonts, design=rules(manifest, head, body))
    return result.fit_report["b1"].final_size_pt


def test_a_neighbour_overlapping_a_fifth_still_shortens_the_zone(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Норма RG39: сосед заходит на пятую часть ширины меньшей зоны (400 000 из
    2 000 000; наименьшее такое перекрытие у шаблонов кейса — 20 %, VK WorkSpace).
    Высота — до него, две строки 24 pt туда не встают, кегль спускается на 18."""
    assert title_size(manifest, fonts, overlap=400_000) == 18


def test_a_hair_of_overlap_does_not_shorten_the_zone(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Нарушитель: 2,3 % ширины меньшей зоны (46 000 из 2 000 000) — не сосед.

    Высота своя, две строки 24 pt в неё встают, кегль прежний."""
    assert title_size(manifest, fonts, overlap=46_000) == 24


# --- Замер на шаблоне кейса --------------------------------------------------------


def test_vk_tech_photo_caption_does_not_overflow() -> None:
    """VK Tech `ex004`, зона z433 «Вставить фото»: сосед z431 заходит на неё на 2,3 %.

    Двустрочная подпись снимается с заметкой, однострочная — цела и в рамке.
    """
    manifest = TemplateParser().parse(case_template("VK Tech шаблон.pptx"))
    design = DesignRules(manifest, derive(manifest))
    frame = next(
        z for r in design.ds.recipes if r.recipe_id == "ex004" for z in r.zones
        if z.zone_id == "z433"
    )
    fonts = FontLibrary.default()

    def run(text: str) -> tuple[SlideIR, list[str]]:
        slide = caption_slide(text).model_copy(update={"layout_id": manifest.layouts[0].layout_id})
        return _fit_shortening(slide, manifest, fonts, CONTENT, design)

    gone, notes = run("Экспорт PDF")
    kept, _ = run("12 слайдов")

    assert gone.blocks == []
    assert "s06/p0: текст «Экспорт PDF» снят — не помещается в место макета даже в два слова" in (
        notes
    )
    fit = kept.fit_report["p0"]
    assert [b.text for b in kept.blocks if isinstance(b, TextBlock)] == ["12 слайдов"]
    assert (fit.final_size_pt, fit.overflow) == (10, False)
    assert fit.required_cy_emu <= (frame.cy or 0) - 2 * TEXT_FRAME_INSET_Y_EMU
