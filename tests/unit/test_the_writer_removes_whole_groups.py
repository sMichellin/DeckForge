"""Писатель снимает незаполненное группами паспорта. Change `the-writer-removes-whole-groups`
(план Б, 4; issue #244).

VK Tech `ex018`: ряд из четырёх карточек и широкая карточка под ним. Legacy-IR 28.09 кладёт текст
в 1-ю и 4-ю карточку ряда, 2-я, 3-я и широкая остаются плашками без текста — на шести слайдах.
С паспортом писатель не угадывает: карточка без нашего текста уходит целиком, а ряд
заполняется с начала. Без паспорта — прежний путь, байт в байт (эталон снят до правки кода).

Шов — `clone_recipe`: синтетический пример python-pptx и настоящие шаблоны кейса.
Сценарии — из дельты `openspec/changes/the-writer-removes-whole-groups/specs/pptx-writer/`.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.util import Emu

from deckforge.designsystem.models import (
    ExamplePassport,
    Place,
    PlaceGroup,
    PlaceKind,
    Recipe,
    RecipeKind,
    TypeLevel,
    Zone,
)
from deckforge.pipeline.replay import from_fixture
from deckforge.rendering.recipe_slide import clone_recipe
from tests.case_templates import case_template
from tests.unit.test_recipe_leaves_no_sample_text import slide_ir

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "the-writer-removes-whole-groups"
RUNS = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-28"
VK_TECH = "VK Tech шаблон.pptx"
WORKSPACE = "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx"

#: Карточки ряда: левый край плашки. Четвёртая карточка собрана в `p:grpSp`.
CARDS = (300000, 2500000, 4700000, 6900000)


def _text_box(shapes, x, y, cx, cy, text):
    box = shapes.add_textbox(Emu(x), Emu(y), Emu(cx), Emu(cy))
    box.text_frame.text = text
    return box


def cards_example():
    """Пример «ряд карточек» на слайде 9144000 × 6858000 EMU.

    Заголовок; четыре карточки ряда — плашка, иконка на ней, подзаголовок и текст (четвёртая
    в группе `p:grpSp`); широкая карточка — плашка, акцентная черта слева от неё и текст; линия от третьей карточки вниз,
    которой нет в паспорте; таблица автора, которую рецепт не адресует.
    """
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    shapes = slide.shapes
    found = {"title": _text_box(shapes, 400000, 200000, 8000000, 600000, "Заголовок примера")}
    for n, x in enumerate(CARDS, start=1):
        target = shapes.add_group_shape().shapes if n == 4 else shapes
        found[f"plate{n}"] = target.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, Emu(x), Emu(1200000), Emu(2000000), Emu(2400000)
        )
        found[f"icon{n}"] = target.add_shape(
            MSO_SHAPE.OVAL, Emu(x + 100000), Emu(1300000), Emu(300000), Emu(300000)
        )
        found[f"sub{n}"] = _text_box(target, x + 100000, 1700000, 1800000, 400000, "Подзаголовок")
        found[f"text{n}"] = _text_box(target, x + 100000, 2200000, 1800000, 1200000, "Текст")
    found["wide_plate"] = shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Emu(300000), Emu(3900000), Emu(8600000), Emu(1200000)
    )
    found["wide_bar"] = shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Emu(150000), Emu(3900000), Emu(100000), Emu(1200000)
    )
    found["wide_text"] = _text_box(shapes, 400000, 4000000, 8400000, 1000000, "Широкий текст")
    found["line"] = shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Emu(5700000), Emu(3400000), Emu(5700000), Emu(3900000)
    )
    found["table"] = shapes.add_table(2, 1, Emu(300000), Emu(5400000), Emu(3000000), Emu(800000))
    found["table"].table.cell(0, 0).text = "Заголовок"
    found["table"].table.cell(1, 0).text = "Текст"
    return prs, str(slide.part.partname), found


def _zone(zone_id, shape, role, repeat=None) -> Zone:
    return Zone(
        zone_id=zone_id,
        xml_id=shape.shape_id,
        role=role,
        repeat=repeat,
        capacity_chars=60,
        x=int(shape.left),
        y=int(shape.top),
        cx=int(shape.width),
        cy=int(shape.height),
    )


def cards_recipe(part_name: str, f, *, passport: bool) -> Recipe:
    """Рецепт примера: зоны `zt`, `zs1..4`/`zb1..4` (подзаголовок/текст карточки), `zw`.

    Паспорт: g01 — заголовок; g02–g05 — ряд `r1`, место 1 — подзаголовок, место 2 — текст,
    декор — плашка и иконка; g06 — широкая карточка с плашкой и чертой. Линии и таблицы в паспорте нет.
    """
    zones = [_zone("zt", f["title"], TypeLevel.SLIDE_TITLE)]
    for n in range(1, 5):
        zones.append(_zone(f"zs{n}", f[f"sub{n}"], TypeLevel.CARD_TITLE, repeat=n - 1))
        zones.append(_zone(f"zb{n}", f[f"text{n}"], TypeLevel.BODY, repeat=n - 1))
    zones.append(_zone("zw", f["wide_text"], TypeLevel.BODY))
    recipe = Recipe(
        recipe_id="ex018",
        example_index=1,
        part_name=part_name,
        kind=RecipeKind.CARDS,
        zones=zones,
        repeats=4,
        repeat_xml_ids=[
            [f[f"{name}{n}"].shape_id for name in ("plate", "sub", "text", "icon")]
            for n in range(1, 5)
        ],
    )
    if not passport:
        return recipe
    return recipe.model_copy(update={"passport": cards_passport(f)})


def _place(number: int, zone: Zone) -> Place:
    return Place(
        place_id=f"p{number:02d}", kind=PlaceKind.TEXT, zone_id=zone.zone_id,
        xml_id=zone.xml_id, role=zone.role, capacity_chars=60,
    )


def cards_passport(f) -> ExamplePassport:
    def zone(zone_id: str, shape, role) -> Zone:
        return _zone(zone_id, shape, role)

    groups = [PlaceGroup(group_id="g01", places=[_place(1, zone("zt", f["title"],
                                                                 TypeLevel.SLIDE_TITLE))])]
    for n in range(1, 5):
        groups.append(PlaceGroup(
            group_id=f"g{n + 1:02d}",
            places=[
                _place(2 * n, zone(f"zs{n}", f[f"sub{n}"], TypeLevel.CARD_TITLE)),
                _place(2 * n + 1, zone(f"zb{n}", f[f"text{n}"], TypeLevel.BODY)),
            ],
            decor_xml_ids=[f[f"plate{n}"].shape_id, f[f"icon{n}"].shape_id],
            row="r1",
        ))
    groups.append(PlaceGroup(
        group_id="g06",
        places=[_place(10, zone("zw", f["wide_text"], TypeLevel.BODY))],
        decor_xml_ids=[f["wide_plate"].shape_id, f["wide_bar"].shape_id],
    ))
    return ExamplePassport(groups=groups)


def slide_xml(slide) -> bytes:
    """XML части слайда — то, что сверяется с эталоном (без zip-меток времени)."""
    return bytes(etree.tostring(slide._element, encoding="utf-8"))


#: IR эталона: заголовок, 1-я карточка целиком и текст 4-й — как legacy-IR 28.09 на `ex018`.
LEGACY_FILL = ["zt", "zs1", "zb1", "zb4"]


def synthetic_legacy_xml() -> bytes:
    prs, part_name, f = cards_example()
    recipe = cards_recipe(part_name, f, passport=False)
    return slide_xml(clone_recipe(prs, recipe, slide_ir(recipe, LEGACY_FILL)))


def vk_tech_legacy_xml() -> bytes:
    """VK Tech `ex018` по первому слайду legacy-IR 28.09, который его берёт, без паспорта."""
    prs = Presentation(str(case_template(VK_TECH)))
    run = from_fixture(RUNS / "vk-tech")
    recipe = next(r for r in run.design_system.recipes if r.recipe_id == "ex018")
    slide = next(s for s in run.deck.slides if s.recipe_id == "ex018")
    return slide_xml(clone_recipe(prs, recipe.model_copy(update={"passport": None}), slide))


def test_without_a_passport_the_synthetic_slide_is_byte_for_byte() -> None:
    """История 4: без паспорта XML слайда равен эталону, снятому до правки."""
    assert synthetic_legacy_xml() == (GOLDEN / "synthetic-legacy.xml").read_bytes()


def test_without_a_passport_the_vk_tech_slide_is_byte_for_byte() -> None:
    """История 4 на настоящем шаблоне: VK Tech `ex018` без паспорта — как до правки."""
    assert vk_tech_legacy_xml() == (GOLDEN / "vk-tech-ex018-legacy.xml").read_bytes()
