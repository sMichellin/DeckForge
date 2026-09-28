"""На слайде осталась пустая карточка примера. Change `the-empty-card-is-found`, RG63,
план Б, строка 3 приёмки (#245).

Судья-VLM видел пустые карточки на 5 слайдах VK Tech из 10, детерминированные проверки
молчали: по RG36 пустая у автора рамка — его композиция. `integrity.empty_group` отличает
нашу пустоту от чужой паспортом примера: группа мест, которую мы должны были заполнить
или снять целиком, осталась на странице без текста. Правило 7: нарушитель и норма.

Сценарии — из дельты `openspec/changes/the-empty-card-is-found/specs/audit-deterministic/`.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.util import Emu

from deckforge.audit.deterministic.integrity import empty_group
from deckforge.audit.registry import CheckUnavailable
from deckforge.designsystem import derive
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
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.domain.template import ExampleShape, ShapeKind, TemplateExample, TemplateManifest
from tests.unit._audit_builders import context_for, deck

CHECK = "integrity.empty_group"
RUNS = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-28"
TEMPLATES = Path(__file__).resolve().parents[1] / "fixtures" / "templates"

#: Рамки примера: заголовок и две карточки ряда — плашка и текст в ней.
TITLE = (400000, 200000, 8000000, 600000)
CARD_A = (400000, 2000000, 3000000, 1500000)
CARD_B = (4400000, 2000000, 3000000, 1500000)
#: `cNvPr id` фигур: заголовок, тексты карточек, плашки карточек.
T, A, B, PLATE_A, PLATE_B = 900, 901, 902, 950, 951


def _zone(zone_id: str, xml_id: int, frame: tuple[int, int, int, int], role: TypeLevel,
          repeat: int | None = None) -> Zone:
    x, y, cx, cy = frame
    return Zone(zone_id=zone_id, xml_id=xml_id, role=role, capacity_chars=60, repeat=repeat,
                x=x, y=y, cx=cx, cy=cy)


def _place(number: int, zone_id: str, xml_id: int, role: TypeLevel) -> Place:
    return Place(place_id=f"p{number:02d}", kind=PlaceKind.TEXT, zone_id=zone_id,
                 xml_id=xml_id, role=role, capacity_chars=60)


ZONES = [
    _zone("zt", T, TITLE, TypeLevel.SLIDE_TITLE),
    _zone("za", A, CARD_A, TypeLevel.BODY, repeat=0),
    _zone("zb", B, CARD_B, TypeLevel.BODY, repeat=1),
]
PASSPORT = ExamplePassport(groups=[
    PlaceGroup(group_id="g01", places=[_place(1, "zt", T, TypeLevel.SLIDE_TITLE)]),
    PlaceGroup(group_id="g02", places=[_place(2, "za", A, TypeLevel.BODY)],
               decor_xml_ids=[PLATE_A], row="r1"),
    PlaceGroup(group_id="g03", places=[_place(3, "zb", B, TypeLevel.BODY)],
               decor_xml_ids=[PLATE_B], row="r1"),
])
RECIPE = Recipe(recipe_id="ex018", example_index=1, kind=RecipeKind.CARDS, zones=ZONES,
                repeats=2, repeat_xml_ids=[[PLATE_A, A], [PLATE_B, B]], passport=PASSPORT)


def _example(text_b: int = 40) -> TemplateExample:
    """Пример шаблона: у автора в карточках текст есть (`text_b` = 0 — карточка B пуста)."""
    def shape(xml_id: int, frame: tuple[int, int, int, int], kind: ShapeKind,
              text: int) -> ExampleShape:
        x, y, cx, cy = frame
        return ExampleShape(shape_id=f"sp{xml_id}", kind=kind, x=x, y=y, cx=cx, cy=cy,
                            xml_id=xml_id, text_len=text)

    return TemplateExample(slide_index=1, shapes=[
        shape(T, TITLE, ShapeKind.TEXT, 20),
        shape(PLATE_A, CARD_A, ShapeKind.SHAPE, 0),
        shape(A, CARD_A, ShapeKind.TEXT, 40),
        shape(PLATE_B, CARD_B, ShapeKind.SHAPE, 0),
        shape(B, CARD_B, ShapeKind.TEXT, text_b),
    ])


def _with_id(shape: object, xml_id: int) -> None:
    shape._element.find(f"./*/{qn('p:cNvPr')}").set("id", str(xml_id))  # type: ignore[attr-defined]


def cards_file(path: Path, *, text_b: str | None, plate_b: bool = True) -> Path:
    """Копия примера после писателя: заголовок, карточка A с текстом, карточка B —
    `text_b` (нет — рамку сняли, `""` — рамка без текста), `plate_b` — плашка осталась."""
    prs = Presentation()
    page = prs.slides.add_slide(prs.slide_layouts[6])
    for xml_id, frame, text in ((T, TITLE, "Три причины"), (A, CARD_A, "Первая причина")):
        box = page.shapes.add_textbox(*(Emu(v) for v in frame))
        box.text_frame.text = text
        _with_id(box, xml_id)
    _with_id(page.shapes.add_shape(MSO_SHAPE.RECTANGLE, *(Emu(v) for v in CARD_A)), PLATE_A)
    if plate_b:
        _with_id(page.shapes.add_shape(MSO_SHAPE.RECTANGLE, *(Emu(v) for v in CARD_B)), PLATE_B)
    if text_b is not None:
        box = page.shapes.add_textbox(*(Emu(v) for v in CARD_B))
        box.text_frame.text = text_b
        _with_id(box, B)
    prs.save(str(path))
    return path


def _slide() -> SlideIR:
    return SlideIR(slide_id="s02", layout_id="L07", variant="A", recipe_id="ex018", blocks=[
        TextBlock(block_id="b0", role=TextRole.TITLE, text="Три причины", zone_id="zt"),
        TextBlock(block_id="b1", role=TextRole.BODY, text="Первая причина", zone_id="za"),
    ])


def run(manifest: TemplateManifest, path: Path | None, *, recipes: list[Recipe] | None = None,
        example: TemplateExample | None = None) -> list:
    with_examples = manifest.model_copy(update={"examples": [example or _example()]})
    design = derive(with_examples).model_copy(update={"recipes": recipes or [RECIPE]})
    ctx = replace(context_for(CHECK, deck(_slide()), with_examples, deck_path=path),
                  design_system=design)
    return list(empty_group(ctx))


def test_a_card_left_without_text_is_a_finding(manifest: TemplateManifest,
                                               tmp_path: Path) -> None:
    """Нарушитель: плашка карточки B осталась, рамку её текста сняли."""
    findings = run(manifest, cards_file(tmp_path / "deck.pptx", text_b=None))

    assert [(f.slide_id, f.evidence["group"], f.evidence["row"]) for f in findings] == [
        ("s02", "g03", "r1")
    ]


def test_an_emptied_frame_is_a_finding_too(manifest: TemplateManifest, tmp_path: Path) -> None:
    """Нарушитель: рамка текста осталась, но пустая, — карточка на слайде та же пустая."""
    findings = run(manifest, cards_file(tmp_path / "deck.pptx", text_b=""))

    assert [f.evidence["group"] for f in findings] == ["g03"]


def test_a_filled_card_is_not_a_finding(manifest: TemplateManifest, tmp_path: Path) -> None:
    """Норма: обе карточки с нашим текстом."""
    assert run(manifest, cards_file(tmp_path / "deck.pptx", text_b="Вторая причина")) == []


def test_a_card_removed_whole_is_not_a_finding(manifest: TemplateManifest,
                                               tmp_path: Path) -> None:
    """Норма: незаполненную карточку писатель снял целиком — пустоты на слайде нет."""
    assert run(manifest, cards_file(tmp_path / "deck.pptx", text_b=None, plate_b=False)) == []


def test_a_card_empty_at_the_author_is_not_a_finding(manifest: TemplateManifest,
                                                     tmp_path: Path) -> None:
    """Норма (RG36): у автора карточка B тоже без текста — это его композиция, не наша."""
    path = cards_file(tmp_path / "deck.pptx", text_b="")

    assert run(manifest, path, example=_example(text_b=0)) == []


def test_without_a_passport_the_repeat_of_the_catalogue_is_checked(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    """Нарушитель без паспорта: пример не прошёл пробную заливку — сверка по повторам.

    Второй рецепт с паспортом значит, что каталог уже прошёл `with_passports`, и у этого
    рецепта паспорта нет по причине, а не потому, что его не считали.
    """
    legacy = RECIPE.model_copy(update={"passport": None})
    other = RECIPE.model_copy(update={"recipe_id": "ex099", "example_index": 99})
    path = cards_file(tmp_path / "deck.pptx", text_b=None)

    findings = run(manifest, path, recipes=[legacy, other])

    assert [f.evidence["group"] for f in findings] == ["repeat1"]


def test_without_the_file_the_check_is_skipped(manifest: TemplateManifest) -> None:
    """Файла нет — «не мерили», а не «чисто»."""
    with pytest.raises(CheckUnavailable):
        run(manifest, None)


def test_the_cards_of_vk_tech_on_28_09(tmp_path: Path) -> None:
    """Мерило: колода VK Tech 28.09, пересобранная писателем из IR фикстуры, — находки
    ровно на шести слайдах `ex018`, где карточки пустые на превью (план Б, строка 3)."""
    template = TEMPLATES / "VK Tech шаблон.pptx"
    if not template.is_file() or not (RUNS / "vk-tech").is_dir():
        pytest.skip("нет шаблона VK Tech или фикстуры прогона 28.09")
    from deckforge.export.pptx import export_pptx
    from deckforge.pipeline.replay import from_fixture, reaudit

    snapshot = from_fixture(RUNS / "vk-tech")
    deck_path = export_pptx(snapshot.deck, snapshot.manifest, template, tmp_path / "deck.pptx",
                            content=snapshot.content, design_system=snapshot.design_system)

    report = asyncio.run(reaudit(replace(snapshot, pptx_path=deck_path))).report

    slides = {f.slide_id for f in report.findings if f.check_id == CHECK}
    assert slides == {"s02", "s03", "s04", "s05", "s07", "s09"}
    recipes = {f.evidence["recipe_id"] for f in report.findings if f.check_id == CHECK}
    assert recipes == {"ex018"}
