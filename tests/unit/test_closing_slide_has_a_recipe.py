"""Структурный слайд не остаётся без композиции шаблона. Change `closing-slide-has-a-recipe`,
таск RG8 (`docs/agents/tasks-24-09.md`).

Во всех прогонах 24.09 без рецепта оставался закрывающий слайд: вида `final` каталог не
нашёл ни у одного шаблона кейса, а `pick_recipe` для структурного места отката не имел —
слайд собирался на пустом макете, без фона и декора шаблона.

Сценарии — из дельты `openspec/changes/closing-slide-has-a-recipe/specs/slide-composition/`.
Синтетический каталог идёт в CI; замер на шаблонах кейса пропускается без их файлов.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deckforge.composition.composer import SlideComposer
from deckforge.composition.recipe_picker import RELATED_KINDS, pick_recipe
from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import TemplateManifest
from deckforge.inference.client import Completion
from deckforge.parsing import TemplateParser
from deckforge.registry import load_variant_profiles
from tests.case_templates import case_template

CONTENT_KINDS = (
    RecipeKind.TEXT,
    RecipeKind.CARDS,
    RecipeKind.TEXT_WITH_PICTURE,
    RecipeKind.METRICS,
)


def recipe(index: int, kind: RecipeKind, *, has_picture: bool = False) -> Recipe:
    return Recipe(
        recipe_id=f"ex{index:03d}",
        example_index=index,
        kind=kind,
        repeats=0,
        zones=[Zone(zone_id="z1", xml_id=1, role=TypeLevel.SLIDE_TITLE, capacity_chars=80)],
        has_picture=has_picture,
    )


def slide(intent: SlideIntent, slide_id: str = "s10") -> SlidePlan:
    return SlidePlan(slide_id=slide_id, intent=intent, headline="Спасибо", fact_refs=["f001"])


#: Каталог шаблона прогона `b5babbdac83f`: все виды, кроме `final`.
WITHOUT_FINAL = [
    recipe(1, RecipeKind.COVER),
    recipe(2, RecipeKind.SECTION),
    recipe(3, RecipeKind.TEXT),
    recipe(4, RecipeKind.CARDS),
    recipe(5, RecipeKind.TEXT_WITH_PICTURE, has_picture=True),
]


# --- сценарии дельты ------------------------------------------------------------------


def test_closing_without_final_takes_a_section() -> None:
    """Нарушитель до правки: `None`, слайд на пустом макете."""
    notes: list[str] = []
    picked = pick_recipe(slide(SlideIntent.CLOSING), WITHOUT_FINAL, notes=notes)

    assert picked is not None and picked.kind is RecipeKind.SECTION
    assert len(notes) == 1
    assert "«final»" in notes[0] and "ex002" in notes[0] and "«section»" in notes[0]


def test_closing_without_structural_kinds_takes_a_fitting_content_recipe() -> None:
    notes: list[str] = []
    content_only = [recipe(3, RecipeKind.TEXT), recipe(4, RecipeKind.CARDS)]

    picked = pick_recipe(slide(SlideIntent.CLOSING), content_only, notes=notes)

    assert picked is not None and picked.kind in CONTENT_KINDS
    assert notes and "«final»" in notes[0] and picked.recipe_id in notes[0]


def test_closing_with_final_takes_final_without_a_note() -> None:
    """Норма: откат не перебивает точное совпадение и о себе не говорит."""
    notes: list[str] = []
    final = recipe(9, RecipeKind.FINAL)

    picked = pick_recipe(slide(SlideIntent.CLOSING), [*WITHOUT_FINAL, final], notes=notes)

    assert picked is final
    assert notes == []


def test_an_empty_catalogue_keeps_the_layout_path() -> None:
    notes: list[str] = []
    assert pick_recipe(slide(SlideIntent.CLOSING), [], notes=notes) is None
    assert notes == []


def test_nothing_that_holds_the_slide_is_named() -> None:
    """Каталог непуст, но всё требует картинку, а ассета нет: `None` с причиной."""
    notes: list[str] = []
    pictures = [recipe(5, RecipeKind.TEXT_WITH_PICTURE, has_picture=True)]

    assert pick_recipe(slide(SlideIntent.CLOSING), pictures, notes=notes) is None
    assert notes and "ни один рецепт" in notes[0]


@pytest.mark.parametrize(
    ("intent", "catalogue", "expected"),
    [
        (
            SlideIntent.TITLE,
            [recipe(2, RecipeKind.SECTION), recipe(3, RecipeKind.TEXT)],
            RecipeKind.SECTION,
        ),
        (
            SlideIntent.SECTION,
            [recipe(1, RecipeKind.COVER), recipe(3, RecipeKind.TEXT)],
            RecipeKind.COVER,
        ),
        (
            SlideIntent.CLOSING,
            [recipe(1, RecipeKind.COVER), recipe(2, RecipeKind.SECTION)],
            RecipeKind.SECTION,
        ),
        (
            SlideIntent.CLOSING,
            [recipe(1, RecipeKind.COVER), recipe(3, RecipeKind.TEXT)],
            RecipeKind.COVER,
        ),
    ],
    ids=["титул→раздел", "раздел→обложка", "финал→раздел первым", "финал→обложка"],
)
def test_related_kinds_come_from_the_table(
    intent: SlideIntent, catalogue: list[Recipe], expected: RecipeKind
) -> None:
    picked = pick_recipe(slide(intent), catalogue)
    assert picked is not None and picked.kind is expected


def test_the_relation_table_covers_every_structural_place() -> None:
    assert set(RELATED_KINDS) == {SlideIntent.TITLE, SlideIntent.SECTION, SlideIntent.CLOSING}


def test_a_content_slide_does_not_take_a_structural_recipe() -> None:
    """Откат только для структурного места: содержательный по-прежнему не берёт разделитель."""
    only_section = [recipe(2, RecipeKind.SECTION)]
    assert pick_recipe(slide(SlideIntent.EVIDENCE, "s03"), only_section) is None


def test_neighbours_are_still_spread() -> None:
    """Два одинаковых разделителя подряд разводятся и на откате."""
    first, second = recipe(2, RecipeKind.SECTION), recipe(7, RecipeKind.SECTION)
    picked = pick_recipe(slide(SlideIntent.CLOSING), [first, second], previous="ex002")
    assert picked is second


# --- композитор -----------------------------------------------------------------------


class FakeLlm:
    model = "fake"

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        payload = {
            "blocks": [
                {"block_id": "b1", "type": "text", "role": "title", "text": "Спасибо за внимание"}
            ]
        }
        return Completion(text=json.dumps(payload, ensure_ascii=False), model=self.model)


async def test_the_composer_reports_the_fallback(manifest: TemplateManifest) -> None:
    design = derive(manifest).model_copy(update={"recipes": WITHOUT_FINAL[:3]})
    content = ContentPackage(
        brief=Brief(purpose="product", audience="правление", target_slides=6, language="ru"),
        facts=[Fact(fact_id="f001", text="Спасибо за внимание")],
    )
    composer = SlideComposer(FakeLlm())

    await composer.compose(
        slide(SlideIntent.CLOSING),
        content,
        manifest,
        load_variant_profiles()["A"],
        seed=1,
        design_system=design,
    )

    assert any("«final»" in note and "ex002" in note for note in composer.notes), composer.notes


# --- замер на шаблонах кейса ----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "VK Tech шаблон.pptx",
        "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx",
        "Шаблон презентации VK Education.pptx",
    ],
)
def test_every_place_of_a_case_deck_gets_a_recipe(name: str) -> None:
    """10 из 10: титул, раздел, закрывающий и содержательный — все по каталогу шаблона.

    Замер 24.09: вида `final` нет ни у одного шаблона кейса, у VK Tech нет и `cover`
    с `section` — до правки на нём без рецепта оставались все три структурных места.
    """
    manifest = TemplateParser().parse(case_template(name), use_cache=False)
    recipes = derive(manifest).recipes
    assert recipes, "каталог шаблона кейса пуст — замер не о том"

    places = [SlideIntent.TITLE, SlideIntent.SECTION, SlideIntent.EVIDENCE, SlideIntent.CLOSING]
    missing = [
        intent.value
        for number, intent in enumerate(places, start=1)
        if pick_recipe(slide(intent, f"s{number:02d}"), recipes) is None
    ]
    assert not missing, f"{name}: без рецепта {missing}"
