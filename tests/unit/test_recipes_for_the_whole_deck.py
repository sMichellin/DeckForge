"""Примеры на всю колоду до текста. Change `recipes-for-the-whole-deck` (план Б, шаг 2).

Сценарии — из дельты `openspec/changes/recipes-for-the-whole-deck/specs/slide-composition/`.
Каталог синтетический: проверяется правило выбора, а не конкретный шаблон. Замер строк
приёмки 1 и 2 идёт на фикстурах прогонов 28.09 последним тестом — он же мерило change.
"""

from __future__ import annotations

from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest

from deckforge.composition.assign import MAX_USES, RecipeAssignment, assign_recipes
from deckforge.composition.passport import with_passports
from deckforge.designsystem.models import (
    DesignSystem,
    ExamplePassport,
    GridSpec,
    Place,
    PlaceGroup,
    PlaceKind,
    Recipe,
    RecipeKind,
    SpacingScale,
    ThemeInfo,
    TypeLevel,
    Zone,
)
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import DeckPlan, SlidePlan
from deckforge.domain.template import Margins
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.replay import from_fixture

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-28"
STRUCTURAL_INTENTS = {"title", "section", "closing"}


def text_place(place_id: str, zone_id: str, role: TypeLevel = TypeLevel.BODY) -> Place:
    return Place(
        place_id=place_id, kind=PlaceKind.TEXT, zone_id=zone_id, role=role, capacity_chars=90
    )


def single_group(index: int) -> PlaceGroup:
    return PlaceGroup(
        group_id=f"g{index:02d}", places=[text_place(f"p{index:02d}", f"z{index:02d}")]
    )


def passport(row: int = 0) -> ExamplePassport:
    """Заголовок слайда и ряд из `row` одинаковых карточек; `row=0` — только одиночные места."""
    groups = [
        PlaceGroup(group_id="g01", places=[text_place("p01", "z01", TypeLevel.SLIDE_TITLE)])
    ]
    if not row:
        groups.append(single_group(2))
        return ExamplePassport(groups=groups)
    groups += [
        PlaceGroup(
            group_id=f"g{index + 2:02d}",
            places=[text_place(f"p{index + 2:02d}", f"z{index + 2:02d}", TypeLevel.CARD_TITLE)],
            row="r1",
        )
        for index in range(row)
    ]
    return ExamplePassport(groups=groups)


def recipe(
    recipe_id: str,
    kind: RecipeKind,
    *,
    row: int = 0,
    with_passport: bool = True,
    layout_name: str = "Контент",
) -> Recipe:
    card = passport(row) if with_passport else None
    zones = [Zone(zone_id=place.zone_id or "", role=place.role or TypeLevel.BODY,
                  capacity_chars=90)
             for place in (card.places if card else [])]
    return Recipe(
        recipe_id=recipe_id,
        example_index=int(recipe_id[2:]),
        kind=kind,
        zones=zones or [Zone(zone_id="z01", role=TypeLevel.BODY, capacity_chars=90)],
        repeats=row,
        passport=card,
        layout_name=layout_name,
    )


def design_system(*recipes: Recipe) -> DesignSystem:
    """Дизайн-система с одним заполненным разделом: выбор примера смотрит только в каталог."""
    grid = GridSpec(
        width_emu=12192000,
        height_emu=6858000,
        aspect="16:9",
        margins=Margins(left=685800, right=685800, top=457200, bottom=457200),
        columns=12,
        gutter_emu=152400,
        column_width_emu=736600,
        content_width_emu=10820400,
        content_height_emu=5943600,
        spacing=SpacingScale(base_emu=152400, base_source="gutter", steps_in_margin=4),
    )
    return DesignSystem(
        template_id="sha256:" + "a" * 64,
        source_name="синтетический",
        grid=grid,
        theme=ThemeInfo(),
        recipes=list(recipes),
    )


def slide(
    slide_id: str,
    *,
    intent: SlideIntent = SlideIntent.EVIDENCE,
    visual: str | None = None,
    points: int = 1,
) -> SlidePlan:
    return SlidePlan(
        slide_id=slide_id,
        intent=intent,
        headline=f"Вывод {slide_id}",
        fact_refs=[f"f{index:03d}" for index in range(points)],
        suggested_visual=visual,
    )


def deck(*slides: SlidePlan, seed: int = 1341) -> DeckPlan:
    return DeckPlan(deck_id="d1", variant="A", seed=seed, slides=list(slides))


def assign(plan: DeckPlan, ds: DesignSystem, seed: int = 1341) -> list[RecipeAssignment]:
    return assign_recipes(plan, ds, seed=seed)


# --- пример выбирается на всю колоду --------------------------------------------


def test_every_slide_of_the_plan_gets_an_assignment() -> None:
    """Норма: назначение приходит на каждый слайд плана, а не только на подошедшие."""
    ds = design_system(recipe("ex01", RecipeKind.CARDS, row=3))
    plan = deck(slide("s01", visual="cards", points=3), slide("s02", visual="smartart:process"))

    out = assign(plan, ds)

    assert [item.slide_id for item in out] == ["s01", "s02"]
    assert all(item.reason for item in out), "причина выбора обязана быть у каждого"


def test_the_same_seed_gives_the_same_answer() -> None:
    """Норма: выбор — счёт, а не случайность."""
    ds = design_system(
        recipe("ex01", RecipeKind.CARDS, row=3), recipe("ex02", RecipeKind.CARDS, row=3)
    )
    plan = deck(slide("s01", visual="cards", points=3))

    assert assign(plan, ds) == assign(plan, ds)


def test_an_example_without_a_passport_is_not_a_candidate() -> None:
    """Нарушитель: пример не прошёл пробную заливку, мест у него нет.

    Писать текст под места, которых не смогли померить, нечем (план Б, шаг 1).
    """
    ds = design_system(recipe("ex01", RecipeKind.CARDS, row=3, with_passport=False))

    out = assign(deck(slide("s01", visual="cards", points=3)), ds)

    assert out[0].recipe_id is None


# --- вид примера не подменяется --------------------------------------------------


def test_the_ordered_kind_is_not_substituted() -> None:
    """Нарушитель: заказан вид, которого у шаблона нет.

    Подмена вида — это и есть «ближайший по местам», давший 0 слайдов из 24 на 28.09.
    """
    ds = design_system(recipe("ex01", RecipeKind.TEXT))

    out = assign(deck(slide("s01", visual="kpi")), ds)

    assert out[0].recipe_id is None
    assert "дизайн-систем" in out[0].reason


def test_the_ordered_kind_is_taken_when_the_template_has_it() -> None:
    """Норма: заказанный вид у шаблона есть — он и берётся."""
    ds = design_system(recipe("ex01", RecipeKind.TEXT), recipe("ex02", RecipeKind.METRICS))

    out = assign(deck(slide("s01", visual="kpi")), ds)

    assert out[0].recipe_id == "ex02"


def test_a_visual_that_has_no_example_goes_by_design() -> None:
    """Норма: схему, цитату и callout колода строит своими данными, а не чужими местами."""
    ds = design_system(recipe("ex01", RecipeKind.CARDS, row=3))

    out = assign(deck(slide("s01", visual="smartart:process", points=3)), ds)

    assert out[0].recipe_id is None
    assert "примером не показывается" in out[0].reason


def test_a_slide_without_an_order_is_judged_by_its_shape() -> None:
    """Норма: заказа нет — вид решает форма слайда: два пункта и больше это ряд карточек."""
    ds = design_system(recipe("ex01", RecipeKind.TEXT), recipe("ex02", RecipeKind.CARDS, row=3))

    out = assign(deck(slide("s01", points=3), slide("s02", points=1)), ds)

    assert [item.recipe_id for item in out] == ["ex02", "ex01"]


def test_a_structural_slide_takes_a_related_kind() -> None:
    """Норма: вида `final` у шаблона нет — закрывающий слайд берёт родственный."""
    ds = design_system(recipe("ex01", RecipeKind.SECTION), recipe("ex02", RecipeKind.CARDS, row=3))

    out = assign(deck(slide("s01", intent=SlideIntent.CLOSING)), ds)

    assert out[0].recipe_id == "ex01"
    assert "родственный" in out[0].reason


# --- один пример не занимает колоду ----------------------------------------------


def test_a_third_use_of_the_same_example_is_refused() -> None:
    """Нарушитель: на 28.09 один пример занимал шесть слайдов из десяти."""
    ds = design_system(recipe("ex01", RecipeKind.CARDS, row=3))
    plan = deck(*[slide(f"s{index:02d}", visual="cards", points=3) for index in range(1, 4)])

    out = assign(plan, ds)

    assert [item.recipe_id for item in out] == ["ex01", None, "ex01"]
    assert Counter(item.recipe_id for item in out)["ex01"] == MAX_USES


def test_two_neighbours_do_not_share_an_example() -> None:
    """Норма: соседи известны, потому что выбор идёт последовательно по колоде."""
    ds = design_system(
        recipe("ex01", RecipeKind.CARDS, row=3), recipe("ex02", RecipeKind.CARDS, row=3)
    )
    plan = deck(slide("s01", visual="cards", points=3), slide("s02", visual="cards", points=3))

    out = assign(plan, ds)

    assert out[0].recipe_id != out[1].recipe_id


# --- форма примера ----------------------------------------------------------------


def test_the_row_closest_to_the_points_wins() -> None:
    """Норма: слайду с тремя пунктами достаётся ряд на три, а не на пять."""
    ds = design_system(
        recipe("ex01", RecipeKind.CARDS, row=5), recipe("ex02", RecipeKind.CARDS, row=3)
    )

    out = assign(deck(slide("s01", visual="cards", points=3)), ds)

    assert out[0].recipe_id == "ex02"
    assert out[0].row_fill == {"r1": 3}


def test_a_row_shorter_than_the_slide_loses() -> None:
    """Нарушитель: ряд короче — пункт некуда положить, и такой пример проигрывает."""
    ds = design_system(
        recipe("ex01", RecipeKind.CARDS, row=2), recipe("ex02", RecipeKind.CARDS, row=6)
    )

    out = assign(deck(slide("s01", visual="cards", points=4)), ds)

    assert out[0].recipe_id == "ex02"
    assert out[0].row_fill == {"r1": 4}


def test_an_example_from_a_structural_layout_is_taken_last() -> None:
    """Норма Т8: содержательному слайду пример с титульного макета достаётся последним."""
    ds = design_system(
        recipe("ex01", RecipeKind.TEXT, layout_name="Титульный слайд"),
        recipe("ex02", RecipeKind.TEXT, layout_name="Контент"),
    )

    out = assign(deck(slide("s01", points=1)), ds)

    assert out[0].recipe_id == "ex02"


def test_a_standard_title_and_content_layout_is_not_a_title() -> None:
    """Нарушитель: стандартное «Title and Content» — содержательный макет, а не титул.

    Вид макета по имени берётся из словаря Т8 (`configs/layout_names.yaml`), где «контент»
    стоит раньше «титула». Своими словами в коде этот макет считался титульным, и примеры
    самого ходового макета PowerPoint уходили в конец очереди (замечание тимлида к #248).
    """
    ds = design_system(
        recipe("ex01", RecipeKind.TEXT, layout_name="Title and Content"),
        recipe("ex02", RecipeKind.TEXT, layout_name="Титульный слайд"),
    )

    out = assign(deck(slide("s01", points=1)), ds)

    assert out[0].recipe_id == "ex01", "стандартный макет содержания не должен уходить в конец"


# --- мерило change: строки приёмки 1 и 2 на фикстурах 28.09 -----------------------


@pytest.mark.parametrize("name", ["education", "vk-tech", "workspace"])
def test_the_acceptance_rows_move_on_the_fixtures(name: str) -> None:
    """Мерило change: строки 1 и 2 таблицы приёмки на сохранённых прогонах 28.09.

    «До» (путь `legacy`): пример по смыслу 0 из 8 на каждой колоде, один пример занимал
    4, 6 и 4 слайда, соседей на одном примере 1, 3 и 0.
    """
    run = from_fixture(FIXTURES / name)
    ds, _report = with_passports(run.design_system, run.manifest, FontLibrary.default())

    out = assign_recipes(run.plan, ds, seed=run.plan.seed)

    intents = {item.slide_id: item.intent.value for item in run.plan.slides}
    content = [item for item in out if intents[item.slide_id] not in STRUCTURAL_INTENTS]
    by_meaning = [item for item in content if not item.reason.startswith("заказанного вида нет")]
    ids = [item.recipe_id for item in out]
    uses = Counter(recipe_id for recipe_id in ids if recipe_id)

    assert len(by_meaning) == len(content), "строка 1: пример должен выбираться по смыслу"
    assert max(uses.values(), default=0) <= MAX_USES, "строка 2: один пример на колоду"
    assert not [1 for left, right in pairwise(ids) if left and left == right], "строка 2: подряд"
