"""Структурный слайд выбирает рецепт с местом под свою строку.
Change `a-structural-slide-keeps-its-line` (RG55).

На прогоне `19e3b7e` закрывающие слайды двух колод потеряли содержание: перебор видов
обрывался на первом виде, у которого есть рецепты, даже когда мест под тело у них нет.
У Education это единственный рецепт «final» без мест при наличии мест у «section»,
у WorkSpace — оба рецепта «cover» без мест при отсутствии видов «final» и «section».

Сценарии — из дельты
`openspec/changes/a-structural-slide-keeps-its-line/specs/slide-composition/`.
"""

from __future__ import annotations

from deckforge.composition.recipe_picker import pick_recipe
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan

#: Зона заголовка есть у любого рецепта: она достаётся заголовку слайда, не телу.
TITLE = Zone(zone_id="z1", xml_id=1, role=TypeLevel.SLIDE_TITLE, capacity_chars=80)
#: Свободная зона тела — место под строку структурного слайда.
BODY = Zone(zone_id="z2", xml_id=2, role=TypeLevel.BODY, capacity_chars=120)


def recipe(index: int, kind: RecipeKind, *, seated: bool) -> Recipe:
    return Recipe(
        recipe_id=f"ex{index:03d}",
        example_index=index,
        kind=kind,
        repeats=0,
        zones=[TITLE, BODY] if seated else [TITLE],
    )


def closing(slide_id: str = "s10") -> SlidePlan:
    return SlidePlan(
        slide_id=slide_id,
        intent=SlideIntent.CLOSING,
        headline="Следующий шаг",
        fact_refs=["f001"],
    )


def test_own_kind_without_seats_yields_to_a_related_kind_with_one() -> None:
    """Education: «final» без мест, у «section» место есть — берётся «section»."""
    notes: list[str] = []
    catalogue = [
        recipe(52, RecipeKind.FINAL, seated=False),
        recipe(20, RecipeKind.SECTION, seated=True),
    ]

    picked = pick_recipe(closing(), catalogue, notes=notes)

    assert picked is not None and picked.recipe_id == "ex020"
    assert len(notes) == 1
    assert "«final»" in notes[0] and "ex020" in notes[0]


def test_own_kind_with_a_seat_stays_on_its_kind() -> None:
    """Норма: у своего вида есть рецепт с местом — подмены вида нет."""
    notes: list[str] = []
    catalogue = [
        recipe(52, RecipeKind.FINAL, seated=False),
        recipe(53, RecipeKind.FINAL, seated=True),
        recipe(20, RecipeKind.SECTION, seated=True),
    ]

    picked = pick_recipe(closing(), catalogue, notes=notes)

    assert picked is not None and picked.recipe_id == "ex053"
    assert notes == []


def test_without_own_kind_a_seated_content_recipe_beats_a_seatless_relative() -> None:
    """WorkSpace: вида «final» нет, «cover» без мест, у «text» место есть."""
    notes: list[str] = []
    catalogue = [
        recipe(14, RecipeKind.COVER, seated=False),
        recipe(28, RecipeKind.COVER, seated=False),
        recipe(3, RecipeKind.TEXT, seated=True),
    ]

    picked = pick_recipe(closing(), catalogue, notes=notes)

    assert picked is not None and picked.recipe_id == "ex003"
    assert len(notes) == 1 and "«final»" in notes[0]


def test_no_seats_anywhere_keeps_the_slide_on_its_own_kind() -> None:
    """Норма: мест нет ни у одного рецепта — всё как до правки, свой вид."""
    notes: list[str] = []
    catalogue = [
        recipe(52, RecipeKind.FINAL, seated=False),
        recipe(20, RecipeKind.SECTION, seated=False),
        recipe(3, RecipeKind.TEXT, seated=False),
    ]

    picked = pick_recipe(closing(), catalogue, notes=notes)

    assert picked is not None and picked.recipe_id == "ex052"
    assert notes == []


def test_a_content_slide_is_not_touched() -> None:
    """Содержательный слайд идёт прежним путём: вид заказывает план."""
    catalogue = [
        recipe(3, RecipeKind.TEXT, seated=True),
        recipe(4, RecipeKind.CARDS, seated=True),
    ]
    plan = SlidePlan(
        slide_id="s05",
        intent=SlideIntent.EVIDENCE,
        headline="Что показал замер",
        fact_refs=["f001"],
    )

    picked = pick_recipe(plan, catalogue, notes=[])

    assert picked is not None and picked.kind in (RecipeKind.TEXT, RecipeKind.CARDS)
