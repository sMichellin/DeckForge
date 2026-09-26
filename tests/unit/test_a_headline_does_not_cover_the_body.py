"""Заголовок не накрывает тело, пустая зона не остаётся рамкой. RG39 и RG40
(`docs/agents/tasks-25-09.md`).

Оба дефекта нашлись **глазами на превью** прогонов RG28 и оба вскрылись оттого, что
на слайды вернулось содержание: пока слайд нёс один заголовок, накрывать было нечего
и пустая карточка терялась среди пустого слайда.

RG39. Рамки зон в шаблоне перекрываются: у VK WorkSpace рамка заголовка тянется
до 1 592 263 EMU, а зона тела начинается с 1 243 208. Автору это не мешало — его
заголовок был в одну строку. Наш встал в две и накрыл первую строку тела.

RG40. Повтор рецепта не равен карточке: у VK Tech `ex018` держит ряд из десяти зон
в двух повторах. Два факта занимали две зоны, восемь оставались пустыми рамками —
48 на три колоды.

Шрифт синтетический: каждый знак шириной 0,6 кегля. Шкала синтетического шаблона —
40 / 24 / 18 / 12 (`tests/conftest.py`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Emu

from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import DeckIR, SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.layout.by_design import DesignRules
from deckforge.layout.fitting import fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.parsing import TemplateParser
from deckforge.rendering.writer import PptxWriter
from tests.unit.test_layout_fonts import make_font

#: Зона заголовка: высота своя — 1 200 000 EMU, а до зоны тела под ней — 500 000.
#: Числа в тестах, а не в коде (правило 2).
TITLE_TOP, TITLE_CY = 0, 1_200_000
BODY_TOP = 500_000
WIDE = 6_000_000

#: 40 знаков: при 24 pt в строку зоны влезает 31 (5 817 120 / 182 880), то есть две
#: строки; при 18 pt — 42, то есть одна.
FORTY = "Ручная адаптация шаблонов замедляет ритм"


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=600, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=600)
    return FontLibrary([tmp_path])


def zone(zone_id: str, *, y: int, cy: int, x: int = 0, cx: int = WIDE) -> Zone:
    return Zone(
        zone_id=zone_id, xml_id=int(zone_id[1:]), role=TypeLevel.BODY, capacity_chars=200,
        size_pt=24, x=x, y=y, cx=cx, cy=cy,
    )


def rules(manifest: TemplateManifest, *zones: Zone) -> DesignRules:
    recipe = Recipe(recipe_id="ex018", example_index=18, kind=RecipeKind.TEXT, zones=list(zones))
    ds = derive(manifest).model_copy(update={"recipes": [recipe]})
    return DesignRules(manifest, ds)


def fitted_size(manifest: TemplateManifest, fonts: FontLibrary, *zones: Zone) -> float:
    slide = SlideIR(
        slide_id="s05", layout_id="L07", variant="A", recipe_id="ex018",
        blocks=[TextBlock(block_id="b1", role=TextRole.TITLE, text=FORTY, zone_id="z1")],
    )
    result = fit_slide(slide, manifest, fonts=fonts, design=rules(manifest, *zones))
    return result.fit_report["b1"].final_size_pt


# --- RG39: зона знает о соседе снизу ---------------------------------------------


def test_a_zone_is_measured_down_to_the_next_zone_below(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Нарушитель: зона тела начинается внутри зоны заголовка.

    Своей высоты заголовку хватает на три строки, а до тела — на одну. Текст в две
    строки при 24 pt обязан спуститься на ступень, а не занять чужое место.
    """
    head = zone("z1", y=TITLE_TOP, cy=TITLE_CY)
    body = zone("z2", y=BODY_TOP, cy=1_000_000)

    assert fitted_size(manifest, fonts, head, body) == 18


def test_a_zone_with_nothing_below_keeps_its_own_height(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Норма: под зоной никого — высота своя, и кегль остаётся прежним."""
    head = zone("z1", y=TITLE_TOP, cy=TITLE_CY)

    assert fitted_size(manifest, fonts, head) == 24


def test_a_neighbour_in_another_column_does_not_shrink_the_zone(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Норма: соседняя колонка не сосед снизу.

    Зона справа начинается ниже по вертикали, но по ширине не пересекается — мешать
    она не может, и высоту урезать незачем.
    """
    head = zone("z1", y=TITLE_TOP, cy=TITLE_CY, x=0, cx=WIDE)
    aside = zone("z2", y=BODY_TOP, cy=1_000_000, x=WIDE + 100_000, cx=2_000_000)

    assert fitted_size(manifest, fonts, head, aside) == 24


# --- RG40: пустая зона повтора уходит со слайда -----------------------------------


@pytest.fixture(scope="module")
def row_template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any, Any]:
    """Слайд-пример: заголовок и ряд из трёх подписей в одном повторе.

    Так устроен `ex018` VK Tech: повтор один, зон в нём несколько. Пока пустые зоны
    повтора только очищались, такой ряд давал две заполненные карточки и восемь
    пустых рамок.
    """
    prs = Presentation()
    blank = next(layout for layout in prs.slide_layouts if layout.name == "Blank")
    slide = prs.slides.add_slide(blank)
    title = slide.shapes.add_textbox(Emu(400_000), Emu(300_000), Emu(6_000_000), Emu(600_000))
    title.text_frame.text = "Заголовок примера"
    labels = []
    for n in range(3):
        label = slide.shapes.add_textbox(
            Emu(400_000 + n * 2_600_000), Emu(2_400_000), Emu(2_200_000), Emu(600_000)
        )
        label.text_frame.text = f"Карточка примера {n + 1}"
        labels.append(label.shape_id)

    path = tmp_path_factory.mktemp("row") / "template.pptx"
    prs.save(str(path))
    manifest = TemplateParser().parse(path, use_cache=False)
    recipe = Recipe(
        recipe_id="ex001", example_index=1, part_name=str(slide.part.partname).lstrip("/"),
        kind=RecipeKind.CARDS, repeats=1,
        zones=[
            Zone(zone_id="title", xml_id=title.shape_id, role=TypeLevel.SLIDE_TITLE,
                 capacity_chars=60),
            *[
                Zone(zone_id=f"card{n}", xml_id=xml_id, role=TypeLevel.BODY, repeat=0,
                     capacity_chars=40)
                for n, xml_id in enumerate(labels)
            ],
        ],
        repeat_xml_ids=[labels],
    )
    ds = derive(manifest).model_copy(update={"recipes": [recipe]})
    return path, manifest, ds


def _write(case: tuple[Path, Any, Any], zone_ids: list[str], tmp_path: Path) -> Any:
    """Слайд с заголовком и текстом в названных зонах ряда.

    Заголовок есть всегда: зона заголовка со слайда не удаляется никогда (слайд без
    заголовка читать нечем), и пустой она осталась бы по делу, а не по дефекту.
    """
    path, manifest, ds = case
    slide = SlideIR(
        slide_id="s01", layout_id=manifest.layouts[0].layout_id, variant="A",
        recipe_id="ex001",
        blocks=[
            TextBlock(
                block_id="b0", role=TextRole.TITLE, text="Наш заголовок", zone_id="title"
            ),
            *[
                TextBlock(
                    block_id=f"b{n + 1}", role=TextRole.BODY, text=f"Наш текст {zid}",
                    zone_id=zid,
                )
                for n, zid in enumerate(zone_ids)
            ],
        ],
    )
    deck = DeckIR(
        deck_id="d01", template_id=manifest.template_id, variant="A", seed=1, slides=[slide]
    )
    out = PptxWriter(path, manifest, design_system=ds).write(deck, tmp_path / "deck.pptx")
    return Presentation(str(out)).slides[0]


def _empty_frames(slide: Any) -> int:
    """Текстовые фигуры без текста — ровно то, что считает `check_deck_readable`."""
    return sum(
        1
        for shape in slide.shapes
        if shape.element.find(qn("p:txBody")) is not None and not shape.text_frame.text.strip()
    )


def test_an_unfilled_zone_of_a_repeat_leaves_the_slide(
    row_template: tuple[Path, Any, Any], tmp_path: Path
) -> None:
    """Нарушитель: в ряду три зоны, текста хватило на одну.

    Две оставшиеся раньше очищались и оставались пустыми рамками — на превью это
    пустые карточки рядом с заполненной.
    """
    slide = _write(row_template, ["card0"], tmp_path)

    assert _empty_frames(slide) == 0
    texts = [s.text_frame.text for s in slide.shapes if s.has_text_frame]
    assert "Наш текст card0" in texts
    assert not [text for text in texts if "Карточка примера" in text]


def test_a_filled_row_keeps_every_card(
    row_template: tuple[Path, Any, Any], tmp_path: Path
) -> None:
    """Норма: текста хватило на все три зоны — со слайда не ушло ничего."""
    slide = _write(row_template, ["card0", "card1", "card2"], tmp_path)

    filled = [s.text_frame.text for s in slide.shapes if s.has_text_frame]
    assert sum(1 for text in filled if text.startswith("Наш текст")) == 3
    assert _empty_frames(slide) == 0
