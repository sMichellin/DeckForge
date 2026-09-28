"""Модель паспорта примера. Change `the-example-passport-model` (план Б, шаг 1а, ADR-009).

Паспорт — контракт между потоками A и B: композиция пишет текст под его места, вёрстка
удаляет и перестраивает его группы. Строит паспорт следующий change; здесь проверяются
форма и инварианты, на которые обе стороны будут опираться:

* места ссылаются только на зоны своего рецепта;
* группы одного ряда одной формы — иначе «N × (подзаголовок, текст)» не написать;
* паспорт переживает круг «запись → чтение»: дизайн-система лежит в чекпойнте;
* каталог, собранный до плана Б, читается без паспорта.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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


def zone(zone_id: str, role: TypeLevel = TypeLevel.BODY) -> Zone:
    return Zone(zone_id=zone_id, role=role, capacity_chars=90)


def text(place_id: str, zone_id: str, role: TypeLevel = TypeLevel.BODY, chars: int = 90) -> Place:
    return Place(
        place_id=place_id, kind=PlaceKind.TEXT, zone_id=zone_id, role=role, capacity_chars=chars
    )


def card(group_id: str, first: int, row: str | None = "r1") -> PlaceGroup:
    """Карточка ряда: подзаголовок и текст, плюс плашка без нашего текста."""
    return PlaceGroup(
        group_id=group_id,
        places=[
            text(f"p{first:02d}", f"z{first:02d}", TypeLevel.CARD_TITLE, chars=28),
            text(f"p{first + 1:02d}", f"z{first + 1:02d}"),
        ],
        decor_xml_ids=[100 + first],
        row=row,
    )


def cards_passport() -> ExamplePassport:
    """Заголовок слайда и ряд из трёх карточек."""
    title = PlaceGroup(
        group_id="g01", places=[text("p01", "z01", TypeLevel.SLIDE_TITLE, chars=60)]
    )
    return ExamplePassport(groups=[title, card("g02", 2), card("g03", 4), card("g04", 6)])


def cards_recipe(passport: ExamplePassport | None) -> Recipe:
    return Recipe(
        recipe_id="ex018",
        example_index=18,
        kind=RecipeKind.CARDS,
        zones=[zone(f"z{index:02d}") for index in range(1, 8)],
        repeats=3,
        passport=passport,
    )


def test_a_title_and_a_row_of_cards_is_a_passport() -> None:
    """Норма: одиночная группа и ряд из трёх карточек одной формы."""
    passport = cards_passport()

    assert [group.group_id for group in passport.rows["r1"]] == ["g02", "g03", "g04"]
    assert len(passport.places) == 7
    assert passport.place("p04") is not None and passport.place("p04").zone_id == "z04"


def test_the_passport_survives_a_checkpoint() -> None:
    """Норма: рецепт с паспортом читается из собственного JSON без потерь."""
    recipe = cards_recipe(cards_passport())

    assert Recipe.model_validate_json(recipe.model_dump_json()) == recipe


def test_a_catalogue_before_plan_b_reads_without_a_passport() -> None:
    """Норма: каталог в чекпойнте до 30.09 поля `passport` не несёт."""
    stored = cards_recipe(None).model_dump(mode="json")
    stored.pop("passport")

    assert Recipe.model_validate(stored).passport is None


def test_a_picture_place_has_no_zone() -> None:
    """Норма: картинка держится адресом фигуры, зона и ступень ей не нужны."""
    picture = Place(place_id="p09", kind=PlaceKind.PICTURE, xml_id=42)

    assert picture.shape == (PlaceKind.PICTURE, None)


def test_a_row_of_different_shapes_is_refused() -> None:
    """Нарушитель: в ряду карточка из двух мест и карточка из одного."""
    lonely = PlaceGroup(group_id="g03", places=[text("p04", "z04")], row="r1")

    with pytest.raises(ValidationError, match="разной формы"):
        ExamplePassport(groups=[card("g02", 2), lonely])


def test_a_repeated_place_id_is_refused() -> None:
    """Нарушитель: два места с одним `place_id` — композиция не поймёт, какое заполнять."""
    with pytest.raises(ValidationError, match="места паспорта повторяются"):
        ExamplePassport(groups=[card("g02", 2), card("g03", 2)])


def test_a_place_on_a_foreign_zone_is_refused() -> None:
    """Нарушитель: место ссылается на зону, которой в рецепте нет."""
    stray = ExamplePassport(groups=[PlaceGroup(group_id="g01", places=[text("p01", "z99")])])

    with pytest.raises(ValidationError, match="чужие зоны"):
        cards_recipe(stray)


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": PlaceKind.TEXT, "role": TypeLevel.BODY, "capacity_chars": 90},
        {"kind": PlaceKind.TEXT, "zone_id": "z01", "role": TypeLevel.BODY},
        {"kind": PlaceKind.PICTURE, "zone_id": "z01"},
    ],
    ids=["text-without-zone", "text-without-capacity", "picture-with-zone"],
)
def test_a_place_that_cannot_be_filled_is_refused(fields: dict[str, object]) -> None:
    """Нарушитель: текстовое место без зоны или ёмкости, картинка с зоной."""
    with pytest.raises(ValidationError):
        Place(place_id="p01", **fields)  # type: ignore[arg-type]
