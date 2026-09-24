"""У зоны рецепта есть рамка. Change `zone-carries-its-frame`, таск RG18
(`docs/agents/tasks-24-09.md`).

Разбор примеров рамку фигуры знает (`ExampleShape`, уже в координатах слайда и с масштабом
группы), а каталог её выбрасывал: у `Zone` были только вместимость и кегль. Из-за этого
html верстает слайд по рецепту потоком (RG16) — поставить блок туда же, куда его поставит
PowerPoint, ему не по чему.

Сценарии — из дельты `openspec/changes/zone-carries-its-frame/specs/design-system-extraction/`.
"""

from __future__ import annotations

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import TypeLevel, Zone
from deckforge.domain.template import ExampleShape, TemplateManifest
from deckforge.domain.units import EMU_PER_CM
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template
from tests.unit.designsystem.test_recipes import CASE_TEMPLATES, only, shape, with_example


def _frame(zone: Zone) -> tuple[int | None, int | None, int | None, int | None]:
    return zone.x, zone.y, zone.cx, zone.cy


def _shape_frame(item: ExampleShape) -> tuple[int, int, int, int]:
    return item.x, item.y, item.cx, item.cy


def test_a_zone_carries_the_frame_of_its_shape(manifest: TemplateManifest) -> None:
    """Нарушитель до правки: `x`, `y`, `cx`, `cy` у зоны нет вовсе."""
    title = shape(
        "t",
        x=2 * EMU_PER_CM,
        y=EMU_PER_CM,
        cx=20 * EMU_PER_CM,
        cy=2 * EMU_PER_CM,
        size_pt=32.0,
        xml_id=11,
    )
    body = shape(
        "b",
        x=2 * EMU_PER_CM,
        y=5 * EMU_PER_CM,
        cx=14 * EMU_PER_CM,
        cy=8 * EMU_PER_CM,
        text_len=200,
        xml_id=12,
    )

    zones = {zone.xml_id: zone for zone in only(with_example(manifest, [title, body])).zones}

    assert _frame(zones[11]) == _shape_frame(title)
    assert _frame(zones[12]) == _shape_frame(body)
    assert all(zone.has_frame for zone in zones.values())


def test_the_title_zone_keeps_its_frame_when_its_role_is_named(
    manifest: TemplateManifest,
) -> None:
    """Заголовок, опознанный по месту (`_with_title`), — копия зоны: рамка не теряется."""
    top = shape(
        "t",
        x=2 * EMU_PER_CM,
        y=EMU_PER_CM,
        cx=20 * EMU_PER_CM,
        cy=2 * EMU_PER_CM,
        size_pt=20.0,
        xml_id=21,
    )
    below = shape(
        "b",
        x=2 * EMU_PER_CM,
        y=6 * EMU_PER_CM,
        cx=20 * EMU_PER_CM,
        cy=6 * EMU_PER_CM,
        size_pt=18.0,
        text_len=200,
        xml_id=22,
    )

    recipe = only(with_example(manifest, [top, below]))
    title = next(zone for zone in recipe.zones if zone.role is TypeLevel.SLIDE_TITLE)

    assert title.has_frame
    assert _frame(title) == _shape_frame(top if title.xml_id == 21 else below)


def test_a_frame_past_the_edge_of_the_slide_is_kept_as_it_is(
    manifest: TemplateManifest,
) -> None:
    """Автор завёл фигуру за левый край: рамка не обрезается и не отбрасывается."""
    title = shape(
        "t",
        x=2 * EMU_PER_CM,
        y=EMU_PER_CM,
        cx=20 * EMU_PER_CM,
        cy=2 * EMU_PER_CM,
        size_pt=32.0,
        xml_id=31,
    )
    bleed = shape(
        "b",
        x=-EMU_PER_CM,
        y=5 * EMU_PER_CM,
        cx=14 * EMU_PER_CM,
        cy=8 * EMU_PER_CM,
        text_len=200,
        xml_id=32,
    )

    zones = {zone.xml_id: zone for zone in only(with_example(manifest, [title, bleed])).zones}

    assert _frame(zones[32]) == _shape_frame(bleed)


def test_a_zone_saved_before_this_change_still_validates() -> None:
    """ДС лежит в чекпойнте sqlite: зона без рамки обязана читаться без правок."""
    old = Zone.model_validate(
        {"zone_id": "z5", "xml_id": 5, "role": "slide_title", "capacity_chars": 40}
    )

    assert old.x is None and old.cx is None
    assert not old.has_frame


def test_a_frame_is_complete_or_not_at_all() -> None:
    partial = Zone(zone_id="z5", role=TypeLevel.BODY, capacity_chars=40, x=0, y=0, cx=10)
    assert not partial.has_frame


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_every_zone_of_a_case_template_has_the_frame_of_its_example_shape(name: str) -> None:
    """На настоящих файлах: каждая зона каталога несёт рамку фигуры своего примера."""
    manifest = TemplateParser().parse(case_template(name), use_cache=False)
    recipes = derive(manifest).recipes
    assert recipes, "каталог шаблона кейса пуст — замер не о том"

    by_index = {example.slide_index: example for example in manifest.examples}
    for recipe in recipes:
        shapes = {item.xml_id: item for item in by_index[recipe.example_index].shapes}
        for zone in recipe.zones:
            assert zone.has_frame, f"{name} {recipe.recipe_id}: у {zone.zone_id} нет рамки"
            assert zone.xml_id in shapes, f"{recipe.recipe_id}: фигуры {zone.xml_id} нет"
            assert _frame(zone) == _shape_frame(shapes[zone.xml_id])
