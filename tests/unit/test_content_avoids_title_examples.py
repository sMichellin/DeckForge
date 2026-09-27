"""Содержательный слайд берёт пример с титульного макета последним. Change
`content-avoids-title-examples`, Т8 (`docs/agents/requirements-from-notes-26-09.md`).

Заметка 26.09: «Многие слайды сделаны на титульниках». Каталог композиций намеренно зовёт
насыщенный пример содержательным, на каком бы макете тот ни стоял, и у VK WorkSpace из
27 содержательных рецептов 15 стоят на «N_Титульный слайд». Подборщик их не отличал.

Сценарии — из дельты `openspec/changes/content-avoids-title-examples/specs/`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.composition.recipe_picker import on_title_layout, pick_recipe
from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan
from deckforge.parsing import TemplateParser

TEMPLATES = Path(__file__).resolve().parents[1] / "fixtures" / "templates"
_STRUCTURAL = frozenset({RecipeKind.COVER, RecipeKind.SECTION, RecipeKind.FINAL})


def recipe(index: int, *, repeats: int, titled: bool = False) -> Recipe:
    """Ряд карточек на `repeats` повторов; `titled` — пример стоит на «Титульном» макете."""
    zones = [Zone(zone_id="z1", xml_id=1, role=TypeLevel.SLIDE_TITLE, capacity_chars=90)]
    zones += [
        Zone(zone_id=f"z{n}", xml_id=n, role=TypeLevel.BODY, repeat=n - 2, capacity_chars=200)
        for n in range(2, 2 + repeats)
    ]
    return Recipe(
        recipe_id=f"ex{index:03d}",
        example_index=index,
        kind=RecipeKind.CARDS,
        repeats=repeats,
        zones=zones,
        layout_name="13_Титульный слайд" if titled else "Заголовок и объект",
    )


def slide(intent: SlideIntent = SlideIntent.EVIDENCE, facts: int = 3) -> SlidePlan:
    return SlidePlan(
        slide_id="s03",
        intent=intent,
        headline="Три причины выбрать платформу",
        fact_refs=[f"f{n:03d}" for n in range(1, facts + 1)],
        suggested_visual="cards",
    )


def test_a_content_slide_passes_over_a_title_example() -> None:
    """Нарушитель до правки: титульный пример ближе по повторам — и выбирался он."""
    exact_on_title = recipe(1, repeats=3, titled=True)
    one_off = recipe(2, repeats=4)

    chosen = pick_recipe(slide(), [exact_on_title, one_off])

    assert chosen is not None
    assert chosen.recipe_id == "ex002"


def test_a_title_example_is_taken_when_nothing_else_fits() -> None:
    """Норма: рецепт с титульного макета остаётся в выборе — лучше, чем слайд по макету."""
    only = recipe(1, repeats=3, titled=True)

    chosen = pick_recipe(slide(), [only])

    assert chosen is not None
    assert chosen.recipe_id == "ex001"


def test_seats_still_come_first() -> None:
    """Нехватка мест важнее титульного макета (RG28): с короткого рецепта снимут факт."""
    short = recipe(1, repeats=2)
    on_title = recipe(2, repeats=3, titled=True)

    chosen = pick_recipe(slide(), [short, on_title])

    assert chosen is not None
    assert chosen.recipe_id == "ex002"


def test_a_structural_slide_is_not_touched() -> None:
    """Для титула, раздела и финала признак ничего не меняет: макет им и отведён."""
    cover_on_title = Recipe(
        recipe_id="ex001",
        example_index=1,
        kind=RecipeKind.COVER,
        zones=[Zone(zone_id="z1", xml_id=1, role=TypeLevel.SLIDE_TITLE, capacity_chars=90)],
        layout_name="Титульный слайд",
    )
    cover_plain = cover_on_title.model_copy(
        update={"recipe_id": "ex002", "example_index": 2, "layout_name": "Фото на весь слайд"}
    )

    chosen = pick_recipe(slide(SlideIntent.TITLE, facts=0), [cover_on_title, cover_plain])

    assert chosen is not None
    assert chosen.recipe_id == "ex001"


def test_the_flag_follows_the_layout_name() -> None:
    """Признак — по имени макета через словарь `layout_names.yaml`, не по виду по составу."""

    def named(name: str) -> bool:
        return on_title_layout(recipe(1, repeats=3).model_copy(update={"layout_name": name}))

    assert named("13_Титульный слайд")
    assert named('1_Слайд "Спасибо!"')
    assert named("Титульный слайд раздела")
    assert not named("Заголовок"), "главный содержательный макет VK Education"
    assert not named("N_Контент")
    assert not named("")


@pytest.fixture(scope="module")
def workspace() -> list[Recipe]:
    path = TEMPLATES / "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx"
    if not path.is_file():
        pytest.skip("нет шаблона VK WorkSpace")
    return derive(TemplateParser().parse(path, use_cache=False)).recipes


def test_workspace_marks_its_title_examples(workspace: list[Recipe]) -> None:
    """На «N_Титульный слайд» WorkSpace стоят содержательные рецепты — они помечены."""
    marked = [r for r in workspace if on_title_layout(r) and r.kind not in _STRUCTURAL]

    assert marked, "ни один содержательный рецепт WorkSpace не помечен"
    assert any(not on_title_layout(r) for r in workspace)


def test_workspace_content_slides_leave_title_examples(workspace: list[Recipe]) -> None:
    """Приёмка Т8: где есть вмещающий рецепт не с титульного макета, берётся он."""
    flat = [r.model_copy(update={"layout_name": ""}) for r in workspace]
    marked = {r.recipe_id for r in workspace if on_title_layout(r)}
    before = after = 0
    for facts in (1, 2, 3, 4):
        for visual in (None, "text", "cards", "kpi", "image"):
            plan = slide(facts=facts).model_copy(update={"suggested_visual": visual})
            old, new = pick_recipe(plan, flat), pick_recipe(plan, workspace)
            assert (old is None) == (new is None), "правило оставило слайд без рецепта"
            before += old is not None and old.recipe_id in marked
            after += new is not None and new.recipe_id in marked

    assert after < before
