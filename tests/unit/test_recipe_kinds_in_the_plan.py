"""Виды композиций шаблона в меню плана. Change `recipe-kinds-in-the-plan`, таск 05a.

План называет вид композиции, а конкретный пример выбирает счёт (решение §4 зонтичного
предложения). Чтобы назвать вид, план должен о нём знать — и знать, сколько у него
повторов: иначе он закажет пять пунктов там, где шаблон рисует три.
"""

from __future__ import annotations

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import DesignSystem, Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.template import TemplateManifest
from deckforge.parsing import TemplateParser
from deckforge.planning.visuals import (
    composition_menu,
    design_menu,
    normalize,
    vocabulary,
)
from tests.case_templates import case_template


def recipe(kind: RecipeKind, *, repeats: int = 0, index: int = 1) -> Recipe:
    return Recipe(
        recipe_id=f"ex{index:03d}",
        example_index=index,
        kind=kind,
        repeats=repeats,
        zones=[Zone(zone_id="z1", role=TypeLevel.SLIDE_TITLE, capacity_chars=40)],
    )


def with_recipes(manifest: TemplateManifest, recipes: list[Recipe]) -> DesignSystem:
    return derive(manifest).model_copy(update={"recipes": recipes})


def test_a_template_with_compositions_offers_them_to_the_plan(
    manifest: TemplateManifest,
) -> None:
    ds = with_recipes(manifest, [recipe(RecipeKind.CARDS, repeats=3)])

    orders = {item.order: item.purpose for item in design_menu(ds)}

    assert "cards" in orders
    assert "3 повтора" in orders["cards"], "план должен знать, сколько повторов у шаблона"
    assert "cards" in vocabulary(ds)
    assert normalize("cards", ds) == "cards"


def test_a_template_without_compositions_does_not_offer_them(
    manifest: TemplateManifest,
) -> None:
    """Нарушитель: заказа, который шаблон не умеет, в словаре быть не должно."""
    ds = derive(manifest)

    assert ds.recipes == []
    assert composition_menu(ds) == []
    assert "cards" not in vocabulary(ds)
    assert normalize("cards", ds) is None


def test_the_range_of_repeats_is_named_when_the_template_has_several(
    manifest: TemplateManifest,
) -> None:
    ds = with_recipes(
        manifest,
        [
            recipe(RecipeKind.CARDS, repeats=3, index=1),
            recipe(RecipeKind.CARDS, repeats=5, index=2),
        ],
    )

    purpose = next(item.purpose for item in design_menu(ds) if item.order == "cards")

    assert "3–5 повторов" in purpose


def test_structural_compositions_are_not_ordered_by_the_plan(
    manifest: TemplateManifest,
) -> None:
    """Обложку, перебивку и финал слайд получает по месту в колоде, а не заказом."""
    ds = with_recipes(
        manifest,
        [
            recipe(RecipeKind.COVER),
            recipe(RecipeKind.SECTION, index=2),
            recipe(RecipeKind.FINAL, index=3),
        ],
    )

    assert composition_menu(ds) == []


def test_compositions_stand_before_single_elements(manifest: TemplateManifest) -> None:
    """Слайд целиком по шаблону важнее отдельного элемента на нём."""
    ds = with_recipes(manifest, [recipe(RecipeKind.CARDS, repeats=3)])

    orders = [item.order for item in design_menu(ds)]

    assert orders[0] == "cards"
    assert "quote" in orders, "элементы дизайн-системы из меню не пропали"


def test_an_order_named_twice_is_offered_once(manifest: TemplateManifest) -> None:
    """`kpi` есть и в словаре, и в композициях: в меню он появляется один раз."""
    ds = with_recipes(manifest, [recipe(RecipeKind.METRICS, repeats=4)])

    orders = [item.order for item in design_menu(ds)]

    assert orders.count("kpi") == 1


@pytest.mark.parametrize(
    "name",
    [
        "VK Tech шаблон.pptx",
        "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx",
        "Шаблон презентации VK Education.pptx",
    ],
)
def test_a_case_template_offers_at_least_one_composition(name: str) -> None:
    parsed = TemplateParser().parse(case_template(name), use_cache=False)

    menu = composition_menu(derive(parsed))

    assert menu, f"{name}: шаблон рисует композиции, а плану их не предлагают"
    assert all(item.purpose for item in menu)
