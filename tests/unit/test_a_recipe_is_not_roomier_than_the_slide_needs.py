"""Рецепт не просторнее, чем нужно слайду. Таск RG52,
change `a-recipe-is-not-roomier-than-the-slide-needs`.

Аудит на прогоне Education `de4fac624dc3` дал ноль ошибок, а на превью s06 — чертёж
из стрелок, не ведущих ни к чему. Замер объяснил: рецепту `ex013` досталось девять
мест под тело на один блок, восемь зон сняли как пустые (RG40), а декор между ними
остался. По колоде таких мест было 27 на десяти слайдах, и три слайда из десяти
собраны одним и тем же девятиместным рецептом.

Отбор наказывал нехватку мест (RG28) и не замечал избытка.

Сценарии — из дельты `openspec/changes/a-recipe-is-not-roomier-than-the-slide-needs/`.
"""

from __future__ import annotations

from deckforge.composition.recipe_picker import pick_recipe
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan


def zone(zone_id: str, role: TypeLevel, *, chars: int = 120) -> Zone:
    return Zone(
        zone_id=zone_id, xml_id=int(zone_id[1:]), role=role, capacity_chars=chars, size_pt=16
    )


def recipe(index: int, seats: int, *, repeats: int = 0) -> Recipe:
    """Рецепт с заголовком и `seats` местами под тело."""
    zones = [zone("z1", TypeLevel.SLIDE_TITLE)]
    zones += [zone(f"z{10 + n}", TypeLevel.BODY) for n in range(seats)]
    return Recipe(
        recipe_id=f"ex{index:03d}", example_index=index, kind=RecipeKind.TEXT,
        repeats=repeats, zones=zones,
    )


def plan(facts: int) -> SlidePlan:
    return SlidePlan(
        slide_id="s06",
        intent=SlideIntent.EVIDENCE,
        headline="Автоматически верстаем результат",
        fact_refs=[f"f{n}" for n in range(facts)],
    )


def test_nine_seats_lose_to_two_when_the_slide_has_two_facts() -> None:
    """Нарушитель: девятиместный рецепт доставался слайду с двумя фактами.

    Так и вышло на Education: `ex013` на девять мест собрал три слайда из десяти.
    """
    roomy, snug = recipe(13, seats=9), recipe(24, seats=2)

    chosen = pick_recipe(plan(2), [roomy, snug])

    assert chosen is not None and chosen.recipe_id == "ex024"


def test_a_shortage_still_weighs_more_than_a_surplus() -> None:
    """Норма: потерять факт хуже, чем оставить пустое место."""
    cramped, roomy = recipe(24, seats=2), recipe(13, seats=6)

    chosen = pick_recipe(plan(3), [cramped, roomy])

    assert chosen is not None and chosen.recipe_id == "ex013"


def test_an_exact_fit_wins() -> None:
    """Норма: рецепт ровно по слайду — лучший из всех."""
    exact, roomy, cramped = recipe(5, seats=3), recipe(13, seats=9), recipe(24, seats=1)

    chosen = pick_recipe(plan(3), [roomy, cramped, exact])

    assert chosen is not None and chosen.recipe_id == "ex005"


def test_the_neighbour_rule_still_applies() -> None:
    """Норма: два одинаковых по местам рецепта разводятся соседством, как раньше."""
    first, second = recipe(1, seats=2), recipe(2, seats=2)

    chosen = pick_recipe(plan(2), [first, second], previous="ex001")

    assert chosen is not None and chosen.recipe_id == "ex002"
