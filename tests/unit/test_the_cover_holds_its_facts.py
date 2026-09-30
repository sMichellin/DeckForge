"""Обложка и финал вмещают своё содержание. Change `the-cover-holds-its-facts`.

План Б, круг 2, корень К3. Сценарии — из дельты
`openspec/changes/the-cover-holds-its-facts/specs/slide-composition/`.

На прогоне 29.09 обложка и финал WorkSpace получили `ex014`: место заголовка на 23 знака
при заголовке в 61 и ни одного другого текстового места — два факта финала положить было
некуда (`integrity.content_lost`). Отбор смотрел только на вид примера.
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

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-28"
STRUCTURAL = {"title", "section", "closing"}


def text_place(place_id: str, zone_id: str, role: TypeLevel, chars: int) -> Place:
    return Place(
        place_id=place_id, kind=PlaceKind.TEXT, zone_id=zone_id, role=role,
        capacity_chars=chars,
    )


def passport_of(*places: Place) -> ExamplePassport:
    return ExamplePassport(
        groups=[
            PlaceGroup(group_id=f"g{index:02d}", places=[place])
            for index, place in enumerate(places, start=1)
        ]
    )


def recipe_of(
    recipe_id: str,
    kind: RecipeKind,
    *,
    title_chars: int,
    body_chars: int | None = None,
    title_role: TypeLevel = TypeLevel.SLIDE_TITLE,
) -> Recipe:
    places = [text_place("p01", "z01", title_role, title_chars)]
    if body_chars is not None:
        places.append(text_place("p02", "z02", TypeLevel.BODY, body_chars))
    card = passport_of(*places)
    zones = [
        Zone(zone_id=place.zone_id or "", role=place.role or TypeLevel.BODY,
             capacity_chars=place.capacity_chars)
        for place in card.places
    ]
    return Recipe(
        recipe_id=recipe_id, example_index=int(recipe_id[2:]), kind=kind, zones=zones,
        passport=card, layout_name="Титул",
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


def cover(headline: str, facts: int = 0) -> SlidePlan:
    return SlidePlan(
        slide_id="s01", intent=SlideIntent.TITLE, headline=headline,
        fact_refs=[f"f{index:03d}" for index in range(facts)],
    )


def closing(headline: str, facts: int = 0) -> SlidePlan:
    return SlidePlan(
        slide_id="s10", intent=SlideIntent.CLOSING, headline=headline,
        fact_refs=[f"f{index:03d}" for index in range(facts)],
    )


def deck(*slides: SlidePlan) -> DeckPlan:
    return DeckPlan(deck_id="d1", variant="A", seed=1341, slides=list(slides))


# --- место заголовка --------------------------------------------------------------


def test_a_short_title_place_loses_the_cover() -> None:
    """Нарушитель: место на 23 знака при заголовке в 61 — это обрубок, а не заголовок."""
    tight = recipe_of("ex014", RecipeKind.COVER, title_chars=23)
    slide = cover("Отчёт для правления: как ИИ меняет создание презентаций в компании")

    assert len(slide.headline) > 23
    assert not holds_the_slide(tight, slide)
    out = assign_recipes(deck(slide), design_system(tight), seed=1341)
    assert out[0].recipe_id is None
    assert "23 знаков" in out[0].reason and "заголовок слайда" in out[0].reason


def test_a_roomy_title_place_keeps_the_cover() -> None:
    """Норма: место держит заголовок целиком — пример назначается."""
    roomy = recipe_of("ex003", RecipeKind.COVER, title_chars=64)
    slide = cover("Итоги квартала")

    assert holds_the_slide(roomy, slide)
    assert assign_recipes(deck(slide), design_system(roomy), seed=1341)[0].recipe_id == "ex003"


def test_the_roomiest_title_place_decides() -> None:
    """Норма: место заголовка — самое просторное своей ступени, а не первое попавшееся."""
    wide = recipe_of("ex003", RecipeKind.COVER, title_chars=64, body_chars=20)

    heading = title_place(wide)

    assert heading is not None and heading.capacity_chars == 64


def test_display_is_a_title_on_the_cover_only() -> None:
    """Норма и нарушитель: крупная строка — заголовок обложки, но не плитки показателей."""
    slide = cover("Итоги квартала")
    on_cover = recipe_of("ex028", RecipeKind.COVER, title_chars=40, title_role=TypeLevel.DISPLAY)
    on_tiles = recipe_of("ex019", RecipeKind.METRICS, title_chars=40, title_role=TypeLevel.DISPLAY)

    assert holds_the_slide(on_cover, slide)
    assert title_place(on_tiles) is None
    assert not holds_the_slide(on_tiles, slide)


# --- место под факты --------------------------------------------------------------


def test_a_closing_with_facts_needs_a_place_for_them() -> None:
    """Нарушитель: у примера нет мест кроме заголовка, а план дал финалу два факта."""
    bare = recipe_of("ex014", RecipeKind.FINAL, title_chars=40)
    slide = closing("Что дальше", facts=2)

    assert not holds_the_slide(bare, slide)
    out = assign_recipes(deck(slide), design_system(bare), seed=1341)
    assert out[0].recipe_id is None
    assert "нет места под текст" in out[0].reason and "фактов 2" in out[0].reason


def test_a_closing_without_facts_takes_the_bare_example() -> None:
    """Норма: фактов план не дал — хватит и одного места под заголовок."""
    bare = recipe_of("ex014", RecipeKind.FINAL, title_chars=40)
    slide = closing("Спасибо")

    assert holds_the_slide(bare, slide)
    assert assign_recipes(deck(slide), design_system(bare), seed=1341)[0].recipe_id == "ex014"


def test_a_related_kind_is_taken_when_its_places_hold() -> None:
    """Норма: своего вида нет — берётся родственный, но тоже по местам."""
    tight = recipe_of("ex041", RecipeKind.SECTION, title_chars=10)
    roomy = recipe_of("ex012", RecipeKind.SECTION, title_chars=60, body_chars=90)
    slide = closing("Следующий шаг — пилот", facts=1)

    out = assign_recipes(deck(slide), design_system(tight, roomy), seed=1341)

    assert out[0].recipe_id == "ex012"


# --- содержательный слайд не трогаем ----------------------------------------------


def test_a_content_slide_keeps_its_example() -> None:
    """Нарушитель: тот же порог на содержательном слайде оставил бы колоду без примеров."""
    tight = recipe_of("ex018", RecipeKind.CARDS, title_chars=10, body_chars=90)
    slide = SlidePlan(
        slide_id="s04", intent=SlideIntent.EVIDENCE,
        headline="Согласование стало быстрее на треть", fact_refs=["f001", "f002"],
        suggested_visual="cards",
    )

    assert not holds_the_slide(tight, slide), "по местам он бы не прошёл"
    out = assign_recipes(deck(slide), design_system(tight), seed=1341)
    assert out[0].recipe_id == "ex018", "но содержательному слайду правило не ставится"


# --- мерило на сохранённых прогонах -----------------------------------------------


@pytest.mark.parametrize(
    ("name", "content_with_example"), [("education", 5), ("vk-tech", 4), ("workspace", 8)]
)
def test_structural_slides_hold_their_content_and_row_one_stands(
    name: str, content_with_example: int
) -> None:
    """Мерило change на прогонах 28.09: структурные держат содержание, строка 1 не просела.

    «До»: WorkSpace брал `ex014` на обложку и финал (23 знака в заголовке, мест под текст
    нет), Education — `ex052` и `ex041`. Содержательных слайдов с примером было 8, 4 и 5 —
    столько же должно остаться.
    """
    run = from_fixture(FIXTURES / name)
    ds, _report = with_passports(run.design_system, run.manifest, FontLibrary.default())
    recipes = {recipe.recipe_id: recipe for recipe in ds.recipes}
    plans = {slide.slide_id: slide for slide in run.plan.slides}

    out = assign_recipes(run.plan, ds, seed=run.plan.seed)

    content = [item for item in out if plans[item.slide_id].intent.value not in STRUCTURAL]
    assert sum(1 for item in content if item.recipe_id) == content_with_example

    for item in out:
        slide = plans[item.slide_id]
        if slide.intent.value not in STRUCTURAL or item.recipe_id is None:
            continue
        assert holds_the_slide(recipes[item.recipe_id], slide), (
            f"{name} {item.slide_id}: пример {item.recipe_id} не держит содержание слайда"
        )
