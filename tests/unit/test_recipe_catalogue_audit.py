"""Аудит: рецепт слайда взят из каталога шаблона. Change `recipe-comes-from-the-catalogue`.

Выдумка модели — `recipe_id`, которого в каталоге композиций нет, — прошла 24.09 весь
конвейер и упала в писателе `KeyError` (зонтик `recipe-is-not-the-models-word`). Аудит —
последний слой, который может назвать её по имени. Шов — функция проверки на
`context_for(check_id, deck, manifest)`; каталог проверка считает сама из манифеста.

Нарушитель и норма собираются на настоящем шаблоне кейса: чекпойнтов прогонов локально
нет. Идентификатор нарушителя — строка из прогона `b5babbdac83f`, а не константа шаблона
в коде. Без шаблона в чекауте (CI) эти тесты пропускаются, поэтому нарушитель и норма
на каждую проверку повторены на синтетическом манифесте с одним слайдом-примером.
"""

from __future__ import annotations

import pytest

from deckforge.audit.deterministic.template import recipe_not_in_catalogue, slide_without_recipe
from deckforge.audit.registry import CheckUnavailable
from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.domain.template import (
    ExampleShape,
    ShapeKind,
    TemplateExample,
    TemplateManifest,
)
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template
from tests.unit._audit_builders import context_for, deck

NOT_IN_CATALOGUE = "template.recipe_not_in_catalogue"
WITHOUT_RECIPE = "template.slide_without_recipe"

#: Шаблон прогона `b5babbdac83f`: 29 рецептов `ex001…ex029`.
TEMPLATE = "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx"

#: Что модель назвала рецептом на `s10` прогона `b5babbdac83f`.
INVENTED = "L12_15_title_slide_closing_step_a"


@pytest.fixture(scope="module")
def case() -> tuple[TemplateManifest, list[Recipe]]:
    manifest = TemplateParser().parse(case_template(TEMPLATE), use_cache=False)
    return manifest, derive(manifest).recipes


def recipe_slide(recipe_id: str, zone_ids: list[str], *, slide_id: str) -> SlideIR:
    """Слайд по рецепту: каждый блок стоит в своей зоне."""
    return SlideIR(
        slide_id=slide_id,
        layout_id="L01",
        variant="A",
        recipe_id=recipe_id,
        blocks=[
            TextBlock(block_id=f"b{n}", role=TextRole.BODY, text=f"Текст {n}", zone_id=zone)
            for n, zone in enumerate(zone_ids, start=1)
        ],
    )


def from_catalogue(recipes: list[Recipe], count: int) -> list[SlideIR]:
    """Норма, как `s01…s09` прогона `98a2c58353f3`: рецепты и зоны — из каталога."""
    return [
        recipe_slide(
            recipe.recipe_id,
            [zone.zone_id for zone in recipe.zones],
            slide_id=f"s{n:02d}",
        )
        for n, recipe in enumerate(recipes[:count], start=1)
    ]


def test_a_recipe_the_template_does_not_have_is_an_error(
    case: tuple[TemplateManifest, list[Recipe]],
) -> None:
    """Нарушитель: `s10` из прогона `b5babbdac83f`, рядом девять слайдов из каталога."""
    manifest, recipes = case
    invented = recipe_slide(INVENTED, ["title", "body"], slide_id="s10")
    colony = deck(*from_catalogue(recipes, 9), invented)

    findings = list(recipe_not_in_catalogue(context_for(NOT_IN_CATALOGUE, colony, manifest)))

    assert [(f.slide_id, f.evidence["recipe_id"]) for f in findings] == [("s10", INVENTED)]
    assert findings[0].severity.value == "error"
    assert INVENTED in findings[0].message


def test_recipes_from_the_catalogue_are_not_a_finding(
    case: tuple[TemplateManifest, list[Recipe]],
) -> None:
    """Норма: каждый рецепт каталога этого шаблона — ни одной находки."""
    manifest, recipes = case
    assert len(recipes) == 29, "шаблон прогона b5babbdac83f: 29 рецептов"
    colony = deck(*from_catalogue(recipes, len(recipes)))

    assert list(recipe_not_in_catalogue(context_for(NOT_IN_CATALOGUE, colony, manifest))) == []


def test_a_slide_off_the_catalogue_is_a_note_not_an_error(
    case: tuple[TemplateManifest, list[Recipe]],
) -> None:
    """Нарушитель: каталог есть, а `s03` собран по макету — оговорка уровня info."""
    manifest, recipes = case
    first, second = from_catalogue(recipes, 2)
    plain = SlideIR(
        slide_id="s03",
        layout_id=manifest.layouts[0].layout_id,
        variant="A",
        blocks=[TextBlock(block_id="b1", role=TextRole.TITLE, text="План", placeholder_idx=0)],
    )
    colony = deck(first, second, plain)

    findings = list(slide_without_recipe(context_for(WITHOUT_RECIPE, colony, manifest)))

    assert [f.slide_id for f in findings] == ["s03"]
    assert findings[0].severity.value == "info"


def test_slides_by_the_catalogue_are_not_a_note(
    case: tuple[TemplateManifest, list[Recipe]],
) -> None:
    """Норма: все слайды по рецептам каталога — оговорок нет."""
    manifest, recipes = case
    colony = deck(*from_catalogue(recipes, 9))

    assert list(slide_without_recipe(context_for(WITHOUT_RECIPE, colony, manifest))) == []


# --- синтетика: идёт везде, включая CI ---


def test_without_a_catalogue_the_note_is_skipped_not_passed(
    manifest: TemplateManifest,
) -> None:
    """Каталог пуст (в шаблоне нет примеров) — сравнивать не с чем: пропуск, а не «прошла»."""
    assert derive(manifest).recipes == []
    colony = deck(recipe_slide("ex001", ["z1"], slide_id="s01"))

    with pytest.raises(CheckUnavailable):
        list(slide_without_recipe(context_for(WITHOUT_RECIPE, colony, manifest)))


def test_without_a_catalogue_any_named_recipe_is_invented(
    manifest: TemplateManifest,
) -> None:
    """Каталог пуст — любой названный рецепт выдуман; слайд без рецепта не в счёт."""
    plain = SlideIR(slide_id="s02", layout_id="L01", variant="A", blocks=[])
    colony = deck(recipe_slide(INVENTED, ["title", "body"], slide_id="s01"), plain)

    findings = list(recipe_not_in_catalogue(context_for(NOT_IN_CATALOGUE, colony, manifest)))

    assert [(f.slide_id, f.evidence["recipe_id"]) for f in findings] == [("s01", INVENTED)]


# --- синтетика с непустым каталогом: правило 7 без шаблонов кейса ---


@pytest.fixture
def synthetic(manifest: TemplateManifest) -> tuple[TemplateManifest, list[Recipe]]:
    """Синтетический манифест с одним примером «заголовок и текст» — каталог из одного рецепта.

    Макет — последний, с телом контента: первый у синтетического манифеста титульный
    (так же собирает пример `tests/unit/designsystem/test_recipes.py`).
    """
    width = manifest.slide_size.cx_emu
    shapes = [
        ExampleShape(shape_id="title", kind=ShapeKind.TEXT, x=600_000, y=1_400_000,
                     cx=width // 2, cy=900_000, text_len=40, size_pt=40.0, xml_id=2),
        ExampleShape(shape_id="body", kind=ShapeKind.TEXT, x=600_000, y=3_000_000,
                     cx=width // 2, cy=2_000_000, text_len=40, size_pt=18.0, xml_id=3),
    ]
    example = TemplateExample(
        slide_index=1,
        layout_id=manifest.layouts[-1].layout_id,
        part_name="ppt/slides/slide1.xml",
        shapes=shapes,
    )
    with_catalogue = manifest.model_copy(update={"examples": [example]})
    recipes = derive(with_catalogue).recipes
    assert len(recipes) == 1, "синтетический пример должен дать ровно один рецепт"
    return with_catalogue, recipes


def test_a_mixed_slide_is_a_note(synthetic: tuple[TemplateManifest, list[Recipe]]) -> None:
    """Нарушитель: рецепт из каталога, но один блок стоит вне зон — собран не по рецепту.

    Смешанный слайд ни вписать по макету, ни скопировать по примеру (`SlideIR.by_recipe`
    ложен), поэтому оговорка — несмотря на названный и настоящий `recipe_id`.
    """
    manifest, recipes = synthetic
    (in_zones,) = from_catalogue(recipes, 1)
    stray = TextBlock(block_id="b9", role=TextRole.BODY, text="Вне зон", placeholder_idx=1)
    mixed = in_zones.model_copy(update={"blocks": [*in_zones.blocks, stray]})

    findings = list(slide_without_recipe(context_for(WITHOUT_RECIPE, deck(mixed), manifest)))

    assert [(f.slide_id, f.evidence["recipe_id"]) for f in findings] == [
        ("s01", recipes[0].recipe_id)
    ]
    assert findings[0].severity.value == "info"


def test_an_invented_recipe_next_to_the_catalogue_is_an_error(
    synthetic: tuple[TemplateManifest, list[Recipe]],
) -> None:
    """Нарушитель без шаблонов кейса: рядом со слайдом из каталога — выдуманный рецепт."""
    manifest, recipes = synthetic
    colony = deck(*from_catalogue(recipes, 1), recipe_slide(INVENTED, ["title"], slide_id="s02"))

    findings = list(recipe_not_in_catalogue(context_for(NOT_IN_CATALOGUE, colony, manifest)))

    assert [(f.slide_id, f.evidence["recipe_id"]) for f in findings] == [("s02", INVENTED)]
    assert findings[0].severity.value == "error"


def test_a_recipe_from_the_synthetic_catalogue_is_not_a_finding(
    synthetic: tuple[TemplateManifest, list[Recipe]],
) -> None:
    """Норма без шаблонов кейса: слайд по единственному рецепту каталога."""
    manifest, recipes = synthetic
    colony = deck(*from_catalogue(recipes, 1))

    assert list(recipe_not_in_catalogue(context_for(NOT_IN_CATALOGUE, colony, manifest))) == []


def test_a_layout_slide_next_to_the_catalogue_is_a_note(
    synthetic: tuple[TemplateManifest, list[Recipe]],
) -> None:
    """Нарушитель без шаблонов кейса: каталог непуст, `s02` собран по макету."""
    manifest, recipes = synthetic
    plain = SlideIR(
        slide_id="s02",
        layout_id=manifest.layouts[0].layout_id,
        variant="A",
        blocks=[TextBlock(block_id="b1", role=TextRole.TITLE, text="План", placeholder_idx=0)],
    )
    colony = deck(*from_catalogue(recipes, 1), plain)

    findings = list(slide_without_recipe(context_for(WITHOUT_RECIPE, colony, manifest)))

    assert [f.slide_id for f in findings] == ["s02"]
    assert findings[0].severity.value == "info"


def test_a_slide_by_the_synthetic_catalogue_is_not_a_note(
    synthetic: tuple[TemplateManifest, list[Recipe]],
) -> None:
    """Норма без шаблонов кейса: слайд по рецепту каталога, все блоки в зонах."""
    manifest, recipes = synthetic
    colony = deck(*from_catalogue(recipes, 1))

    assert list(slide_without_recipe(context_for(WITHOUT_RECIPE, colony, manifest))) == []
