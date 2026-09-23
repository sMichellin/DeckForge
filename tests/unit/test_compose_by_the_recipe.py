"""Подбор композиции и текст по её зонам. Change `compose-by-the-recipe`, таск 05b.

Два шва: `pick_recipe` на планах (счёт, без модели) и `bind_to_recipe` на готовом
`SlideIR` (раскладка текста по зонам). Модель в этих тестах не участвует — и не должна:
вид называет план, пример выбирает счёт.
"""

from __future__ import annotations

from deckforge.composition.recipe_binding import bind_to_recipe
from deckforge.composition.recipe_picker import pick_recipe
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import SlideIntent, TextRole
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import BulletItem, BulletsBlock, SlideIR, TextBlock


def zone(zone_id: str, role: TypeLevel, *, repeat: int | None = None, chars: int = 80) -> Zone:
    return Zone(
        zone_id=zone_id, xml_id=int(zone_id[1:]), role=role, repeat=repeat, capacity_chars=chars
    )


def recipe(
    index: int,
    kind: RecipeKind,
    *,
    repeats: int = 0,
    has_picture: bool = False,
    zones: list[Zone] | None = None,
) -> Recipe:
    rows = zones or [zone("z1", TypeLevel.SLIDE_TITLE)]
    return Recipe(
        recipe_id=f"ex{index:03d}",
        example_index=index,
        kind=kind,
        repeats=repeats,
        zones=rows,
        has_picture=has_picture,
    )


def plan(**kwargs: object) -> SlidePlan:
    data: dict[str, object] = {
        "slide_id": "s01",
        "intent": SlideIntent.EVIDENCE,
        "headline": "Заголовок",
        "fact_refs": ["f1", "f2", "f3"],
    }
    data.update(kwargs)
    return SlidePlan(**data)  # type: ignore[arg-type]


# --- подбор --------------------------------------------------------------------


def test_the_plan_names_the_kind_and_the_count_picks_the_example() -> None:
    """У слайда три пункта, у шаблона ряды на три и на четыре — берётся ряд на три."""
    three = recipe(1, RecipeKind.CARDS, repeats=3)
    four = recipe(2, RecipeKind.CARDS, repeats=4)

    picked = pick_recipe(plan(suggested_visual="cards"), [four, three])

    assert picked is three


def test_a_recipe_that_does_not_hold_the_facts_is_dropped() -> None:
    """Нарушитель: повторов меньше, чем пунктов, — такой ряд не берут."""
    small = recipe(1, RecipeKind.CARDS, repeats=2)

    assert pick_recipe(plan(suggested_visual="cards"), [small]) is None


def test_a_recipe_with_a_picture_needs_an_asset() -> None:
    picture = recipe(1, RecipeKind.TEXT_WITH_PICTURE, has_picture=True)

    assert pick_recipe(plan(suggested_visual="image"), [picture]) is None
    assert pick_recipe(plan(suggested_visual="image"), [picture], has_asset=True) is picture


def test_two_neighbours_do_not_take_the_same_composition() -> None:
    """Одинаковые соседние слайды читаются как один перелистнутый назад."""
    first = recipe(1, RecipeKind.CARDS, repeats=3)
    second = recipe(2, RecipeKind.CARDS, repeats=3)

    picked = pick_recipe(plan(suggested_visual="cards"), [first, second], previous="ex001")

    assert picked is second


def test_a_structural_slide_takes_a_composition_of_its_own_kind() -> None:
    cover = recipe(1, RecipeKind.COVER)
    cards = recipe(2, RecipeKind.CARDS, repeats=3)

    picked = pick_recipe(plan(intent=SlideIntent.TITLE, fact_refs=[]), [cards, cover])

    assert picked is cover


def test_a_kind_the_template_does_not_have_falls_back_to_any_fitting_one() -> None:
    """Нет композиции названного вида — берётся любая вмещающая, а не прежний путь."""
    text = recipe(1, RecipeKind.TEXT)

    assert pick_recipe(plan(suggested_visual="cards", fact_refs=[]), [text]) is text


def test_a_template_without_compositions_keeps_the_old_path() -> None:
    assert pick_recipe(plan(), []) is None


# --- текст по зонам -------------------------------------------------------------


def slide_ir(blocks: list[object]) -> SlideIR:
    return SlideIR(
        slide_id="s01",
        layout_id="L07",
        variant="A",
        blocks=blocks,  # type: ignore[arg-type]
    )


def test_every_bullet_gets_its_own_repeat() -> None:
    """У шаблона ряд карточек, а не список на три строки: каждый пункт — своя карточка."""
    cards = recipe(
        1,
        RecipeKind.CARDS,
        repeats=3,
        zones=[
            zone("z1", TypeLevel.SLIDE_TITLE),
            zone("z10", TypeLevel.CARD_TITLE, repeat=0),
            zone("z11", TypeLevel.CARD_TITLE, repeat=1),
            zone("z12", TypeLevel.CARD_TITLE, repeat=2),
        ],
    )
    composed = slide_ir(
        [
            TextBlock(block_id="t", role=TextRole.TITLE, text="Заголовок"),
            BulletsBlock(
                block_id="b",
                role=TextRole.BODY,
                items=[BulletItem(text="Раз"), BulletItem(text="Два"), BulletItem(text="Три")],
            ),
        ]
    )

    bound = bind_to_recipe(composed, cards)

    assert bound.recipe_id == "ex001"
    assert [block.zone_id for block in bound.blocks] == ["z1", "z10", "z11", "z12"]
    assert [block.text for block in bound.blocks] == ["Заголовок", "Раз", "Два", "Три"]
    assert all(block.bbox is None for block in bound.blocks), "рамку даёт автор шаблона"


def test_the_heading_takes_the_title_zone_even_inside_a_repeat() -> None:
    """Нарушитель: каталог отнёс зону заголовка к повтору.

    Заголовок один на слайд: он забирает свою зону, а пункты обходят её стороной, — иначе
    в шапке слайда оказывается первый пункт списка, а один повтор остаётся пустым.
    """
    cards = recipe(
        1,
        RecipeKind.CARDS,
        repeats=3,
        zones=[
            zone("z10", TypeLevel.BODY, repeat=0),
            zone("z11", TypeLevel.BODY, repeat=1),
            zone("z12", TypeLevel.BODY, repeat=2),
            zone("z50", TypeLevel.SLIDE_TITLE, repeat=1),
        ],
    )
    composed = slide_ir(
        [
            TextBlock(block_id="t", role=TextRole.TITLE, text="Заголовок"),
            BulletsBlock(
                block_id="b",
                role=TextRole.BODY,
                items=[BulletItem(text="Раз"), BulletItem(text="Два"), BulletItem(text="Три")],
            ),
        ]
    )

    bound = bind_to_recipe(composed, cards)

    assert [block.zone_id for block in bound.blocks] == ["z50", "z10", "z11", "z12"]
    assert [block.text for block in bound.blocks] == ["Заголовок", "Раз", "Два", "Три"]


def test_the_text_is_clipped_to_the_capacity_of_the_zone() -> None:
    """Зона — рамка автора, растянуть её нельзя: текст обрезается по словам."""
    tight = recipe(1, RecipeKind.TEXT, zones=[zone("z1", TypeLevel.SLIDE_TITLE, chars=12)])
    composed = slide_ir(
        [TextBlock(block_id="t", role=TextRole.TITLE, text="Очень длинный заголовок слайда")]
    )

    bound = bind_to_recipe(composed, tight)

    assert len(bound.blocks[0].text) <= 12
    assert bound.blocks[0].text == "Очень"


def test_a_block_without_a_zone_leaves_the_slide() -> None:
    """Блок, которому зоны не досталось, вёрстка не нарисует — в отчёте его быть не должно."""
    one = recipe(1, RecipeKind.TEXT, zones=[zone("z1", TypeLevel.SLIDE_TITLE)])
    composed = slide_ir(
        [
            TextBlock(block_id="t", role=TextRole.TITLE, text="Заголовок"),
            TextBlock(block_id="x", role=TextRole.BODY, text="Лишний абзац"),
        ]
    )

    bound = bind_to_recipe(composed, one)

    assert [block.block_id for block in bound.blocks] == ["t"]
