"""Фигура принадлежит ровно одной группе паспорта. Change `a-shape-lives-in-one-group`.

План Б, круг 2, находка стыка A ↔ B. Сценарии — из дельты
`openspec/changes/a-shape-lives-in-one-group/specs/slide-composition/`.

Группа паспорта — то, что уходит со слайда целиком (шаг 4). У Education `ex045` картинка
`1001` была местом группы `g04` и декором заполненной карточки `g03`: снятие пустой `g04`
уносило иллюстрацию заполненной. Писатель от этого защищён (#264), но защищаться ему
приходилось от паспорта, а не от шаблона.

Замер здесь — подделка `fits` по длине текста, как в тесте паспорта: модульный тест
не зависит от шрифтов образа.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from deckforge.composition.passport import Fits, build_passport, with_passports
from deckforge.designsystem.models import (
    ExamplePassport,
    PlaceGroup,
    PlaceKind,
    Recipe,
    RecipeKind,
    TypeLevel,
    Zone,
)
from deckforge.domain.template import ExampleShape, ShapeKind, TemplateExample
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.replay import from_fixture

CM = 360_000
SLIDE_AREA = 12_000_000 * 6_750_000
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-29"


def shape(
    xml_id: int, x: float, y: float, cx: float, cy: float, *, z: int, text: int = 0,
    picture: bool = False,
) -> ExampleShape:
    kind = ShapeKind.PICTURE if picture else (ShapeKind.TEXT if text else ShapeKind.SHAPE)
    return ExampleShape(
        shape_id=f"s{xml_id}", kind=kind, x=int(x * CM), y=int(y * CM),
        cx=int(cx * CM), cy=int(cy * CM), z=z, xml_id=xml_id, text_len=text,
    )


def zone_of(item: ExampleShape, role: TypeLevel) -> Zone:
    return Zone(
        zone_id=f"z{item.xml_id}", xml_id=item.xml_id, role=role, capacity_chars=100,
        size_pt=12.0, x=item.x, y=item.y, cx=item.cx, cy=item.cy,
    )


def limits(caps: dict[str, int]) -> Fits:
    def fits(recipe: Recipe, texts: dict[str, str]) -> dict[str, bool]:
        return {zone_id: len(text) <= caps.get(zone_id, 0) for zone_id, text in texts.items()}

    return fits


def card_with_a_picture() -> tuple[Recipe, TemplateExample]:
    """Карточка-повтор, в адреса которой попала картинка примера.

    Так устроен `ex045` Education: карточка найдена не по подложке, а по повтору каталога
    (`repeat_xml_ids`), и в его адресах стоит та же фигура, на которую смотрит
    `picture_xml_id`. Подложечная ветка картинку исключает, а эта — нет.
    """
    title = shape(100, 1, 0.5, 20, 1.5, z=60, text=30)
    picture = shape(201, 1.5, 3.5, 8, 3, z=20, picture=True)
    line = shape(202, 1.5, 6.8, 8, 0.1, z=25)
    body = shape(203, 1.5, 7, 8, 1.5, z=30, text=40)
    shapes = [title, picture, line, body]
    card = zone_of(body, TypeLevel.BODY).model_copy(update={"repeat": 0})
    recipe = Recipe(
        recipe_id="ex045", example_index=45, kind=RecipeKind.TEXT_WITH_PICTURE,
        zones=[zone_of(title, TypeLevel.SLIDE_TITLE), card],
        repeats=1, repeat_xml_ids=[[picture.xml_id or 0, line.xml_id or 0, body.xml_id or 0]],
        has_picture=True, picture_xml_id=picture.xml_id, layout_name="Контент",
    )
    return recipe, TemplateExample(slide_index=45, layout_id="L07", shapes=shapes)


def made(recipe: Recipe, example: TemplateExample, caps: dict[str, int]) -> ExamplePassport:
    card = build_passport(recipe, example, limits(caps), slide_area=SLIDE_AREA)
    assert not isinstance(card, str), card
    return card


def crossings(groups: list[PlaceGroup]) -> list[int]:
    """Фигуры, записанные больше чем в одну группу: места и декор вместе."""
    counted: Counter[int] = Counter()
    for group in groups:
        counted.update(place.xml_id for place in group.places if place.xml_id is not None)
        counted.update(group.decor_xml_ids)
    return sorted(xml_id for xml_id, times in counted.items() if times > 1)


# --- место сильнее декора ----------------------------------------------------------


def test_a_picture_place_is_not_decor_of_another_group() -> None:
    """Нарушитель: картинка — место своей группы, и декором карточки она не записывается."""
    recipe, example = card_with_a_picture()

    card = made(recipe, example, {"z100": 90, "z203": 90})

    picture = next(place for place in card.places if place.kind is PlaceKind.PICTURE)
    assert picture.xml_id == 201
    assert crossings(card.groups) == [], "фигура живёт ровно в одной группе"
    assert all(201 not in group.decor_xml_ids for group in card.groups)
    assert any(202 in group.decor_xml_ids for group in card.groups), "линия декором осталась"


def test_the_group_of_the_picture_keeps_its_shape() -> None:
    """Норма: правка убирает пересечение, а не саму картинку — место остаётся."""
    recipe, example = card_with_a_picture()

    card = made(recipe, example, {"z100": 90, "z203": 90})

    assert [place.kind for place in card.places].count(PlaceKind.PICTURE) == 1


def test_a_passport_without_crossings_is_untouched() -> None:
    """Норма: пересечений нет — паспорт не меняется ни одной фигурой."""
    title = shape(100, 1, 0.5, 20, 1.5, z=60, text=30)
    plate = shape(200, 1, 3, 9, 6, z=10)
    body = shape(201, 1.5, 3.5, 8, 2, z=20, text=40)
    recipe = Recipe(
        recipe_id="ex001", example_index=1, kind=RecipeKind.TEXT,
        zones=[zone_of(title, TypeLevel.SLIDE_TITLE), zone_of(body, TypeLevel.BODY)],
        layout_name="Контент",
    )
    example = TemplateExample(slide_index=1, layout_id="L07", shapes=[title, plate, body])

    card = made(recipe, example, {"z100": 90, "z201": 90})

    assert crossings(card.groups) == []
    assert 200 in {xml_id for group in card.groups for xml_id in group.decor_xml_ids}, (
        "подложка осталась декором своей карточки"
    )


# --- мерило на шаблонах кейса ------------------------------------------------------


@pytest.mark.parametrize("name", ["education", "vk-tech", "workspace"])
def test_no_shape_is_in_two_groups_on_the_case_templates(name: str) -> None:
    """Мерило change: на трёх шаблонах пересечений не остаётся ни одного.

    «До»: одно на 120 примеров — `ex045` Education, фигура `1001`.
    """
    run = from_fixture(FIXTURES / name)
    ds, _report = with_passports(run.design_system, run.manifest, FontLibrary.default())

    shared = {
        recipe.recipe_id: crossings(recipe.passport.groups)
        for recipe in ds.recipes
        if recipe.passport is not None and crossings(recipe.passport.groups)
    }

    assert shared == {}
