"""Финалу и обложке нужна строка, а не только заголовок. Change `the-closing-says-the-next-step`.

План Б, круг 2, доделка К3 по прогону 29.09. Сценарии — из дельты
`openspec/changes/the-closing-says-the-next-step/specs/slide-composition/`.

После #280 строка 9 стала 0 / 0 / 1: финал Education взял `ex012` вида «раздел» —
место заголовка на 56 знаков и ни одного места под текст, — и вышел одной строкой
(`integrity.empty_slide`). Отбор пропустил его потому, что `fact_refs` у финала пуст,
а строку следующего шага промпт берёт из брифа, а не из фактов плана.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.composition.assign import assign_recipes, holds_the_slide, title_place
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

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-29"
STRUCTURAL = {"title", "section", "closing"}


def text_place(place_id: str, zone_id: str, role: TypeLevel, chars: int) -> Place:
    return Place(
        place_id=place_id, kind=PlaceKind.TEXT, zone_id=zone_id, role=role,
        capacity_chars=chars,
    )


def recipe_of(
    recipe_id: str, kind: RecipeKind, *, title_chars: int, body_chars: int | None = None
) -> Recipe:
    places = [text_place("p01", "z01", TypeLevel.SLIDE_TITLE, title_chars)]
    if body_chars is not None:
        places.append(text_place("p02", "z02", TypeLevel.BODY, body_chars))
    card = ExamplePassport(
        groups=[
            PlaceGroup(group_id=f"g{index:02d}", places=[place])
            for index, place in enumerate(places, start=1)
        ]
    )
    zones = [
        Zone(zone_id=place.zone_id or "", role=place.role or TypeLevel.BODY,
             capacity_chars=place.capacity_chars)
        for place in card.places
    ]
    return Recipe(
        recipe_id=recipe_id, example_index=int(recipe_id[2:]), kind=kind, zones=zones,
        passport=card, layout_name="Раздел",
    )


def design_system(*recipes: Recipe) -> DesignSystem:
    grid = GridSpec(
        width_emu=12192000, height_emu=6858000, aspect="16:9",
        margins=Margins(left=685800, right=685800, top=457200, bottom=457200),
        columns=12, gutter_emu=152400, column_width_emu=736600,
        content_width_emu=10820400, content_height_emu=5943600,
        spacing=SpacingScale(base_emu=152400, base_source="gutter", steps_in_margin=4),
    )
    return DesignSystem(
        template_id="sha256:" + "a" * 64, source_name="синтетический",
        grid=grid, theme=ThemeInfo(), recipes=list(recipes),
    )


def slide(intent: SlideIntent, headline: str = "Разработка сервиса", facts: int = 0) -> SlidePlan:
    return SlidePlan(
        slide_id="s10", intent=intent, headline=headline,
        fact_refs=[f"f{index:03d}" for index in range(facts)],
    )


def deck(*slides: SlidePlan) -> DeckPlan:
    return DeckPlan(deck_id="d1", variant="A", seed=1341, slides=list(slides))


# --- финал и обложка --------------------------------------------------------------


def test_a_closing_without_facts_still_needs_a_line() -> None:
    """Нарушитель: у примера только заголовок — финалу он не годится и без фактов.

    Это `ex012` Education: 56 знаков в заголовке и ни одного места под текст.
    """
    bare = recipe_of("ex012", RecipeKind.SECTION, title_chars=56)
    final = slide(SlideIntent.CLOSING)

    assert not final.fact_refs
    assert not holds_the_slide(bare, final)
    assert assign_recipes(deck(final), design_system(bare), seed=1341)[0].recipe_id is None


def test_a_closing_takes_an_example_with_a_line() -> None:
    """Норма: место под текст есть — пример финалу назначается."""
    roomy = recipe_of("ex003", RecipeKind.COVER, title_chars=23, body_chars=23)
    final = slide(SlideIntent.CLOSING)

    assert holds_the_slide(roomy, final)
    assert assign_recipes(deck(final), design_system(roomy), seed=1341)[0].recipe_id == "ex003"


def test_a_cover_without_facts_needs_a_line_too() -> None:
    """Нарушитель: обложке строка «о чём колода и для кого» нужна так же."""
    bare = recipe_of("ex028", RecipeKind.COVER, title_chars=40)
    cover = slide(SlideIntent.TITLE, headline="Итоги квартала")

    assert not holds_the_slide(bare, cover)


def test_a_section_is_a_line_by_itself() -> None:
    """Норма: раздел — одна строка между частями колоды, второго места ему не нужно."""
    bare = recipe_of("ex041", RecipeKind.SECTION, title_chars=40)
    part = SlidePlan(slide_id="s05", intent=SlideIntent.SECTION, headline="Часть вторая")

    assert holds_the_slide(bare, part)
    assert assign_recipes(deck(part), design_system(bare), seed=1341)[0].recipe_id == "ex041"


def test_a_slide_with_facts_behaves_as_before() -> None:
    """Норма: факты требуют места, как и требовали."""
    bare = recipe_of("ex012", RecipeKind.SECTION, title_chars=56)
    roomy = recipe_of("ex003", RecipeKind.SECTION, title_chars=56, body_chars=40)
    part = SlidePlan(
        slide_id="s05", intent=SlideIntent.SECTION, headline="Часть вторая",
        fact_refs=["f001"],
    )

    assert not holds_the_slide(bare, part)
    assert holds_the_slide(roomy, part)


def test_the_headline_still_has_to_fit() -> None:
    """Норма: правило про заголовок осталось — место короче заголовка не проходит."""
    tight = recipe_of("ex014", RecipeKind.COVER, title_chars=23, body_chars=40)
    cover = slide(SlideIntent.TITLE, headline="О" * 61)

    assert not holds_the_slide(tight, cover)


# --- мерило на сохранённом прогоне ------------------------------------------------


@pytest.mark.parametrize("name", ["education", "vk-tech", "workspace"])
def test_every_structural_example_has_a_place_for_its_line(name: str) -> None:
    """Мерило change на прогоне 29.09: у обложки и финала с примером есть место под текст.

    «До»: финал Education получал `ex012` — только заголовок, и слайд вышел одной строкой.
    """
    run = from_fixture(FIXTURES / name)
    ds, _report = with_passports(run.design_system, run.manifest, FontLibrary.default())
    recipes = {recipe.recipe_id: recipe for recipe in ds.recipes}
    plans = {slide.slide_id: slide for slide in run.plan.slides}

    for item in assign_recipes(run.plan, ds, seed=run.plan.seed):
        plan = plans[item.slide_id]
        if item.recipe_id is None or plan.intent not in {SlideIntent.TITLE, SlideIntent.CLOSING}:
            continue
        recipe = recipes[item.recipe_id]
        heading = title_place(recipe)
        body = [
            place
            for place in (recipe.passport.places if recipe.passport else [])
            if place is not heading and place.kind is PlaceKind.TEXT
        ]
        assert body, f"{name} {item.slide_id}: {item.recipe_id} даёт только заголовок"
