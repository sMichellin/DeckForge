"""Каталог композиций шаблона. Change `recipes-in-the-design-system`, таск 03a.

Шов один — `recipes(manifest, ds)`. Синтетический манифест строит по примеру на каждый
вид, чтобы правило разбора проверялось на норме и на нарушителе; три шаблона кейса
проверяют, что правило работает на настоящих файлах, а не только на выдуманных.
"""

from __future__ import annotations

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import RecipeKind, TypeLevel
from deckforge.designsystem.recipes import (
    CHAR_WIDTH_RATIO,
    LINE_HEIGHT_RATIO,
    kind_for_visual,
)
from deckforge.domain.template import (
    ComponentKind,
    ComponentSpec,
    ExampleShape,
    ShapeKind,
    TemplateExample,
    TemplateManifest,
)
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template

CASE_TEMPLATES = [
    "VK Tech шаблон.pptx",
    "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx",
    "Шаблон презентации VK Education.pptx",
]


def shape(
    shape_id: str,
    *,
    x: int,
    y: int,
    cx: int,
    cy: int,
    kind: ShapeKind = ShapeKind.TEXT,
    text_len: int = 40,
    size_pt: float | None = 18.0,
    xml_id: int | None = None,
) -> ExampleShape:
    return ExampleShape(
        shape_id=shape_id,
        kind=kind,
        x=x,
        y=y,
        cx=cx,
        cy=cy,
        text_len=text_len,
        size_pt=size_pt,
        xml_id=xml_id,
    )


def with_example(
    manifest: TemplateManifest,
    shapes: list[ExampleShape],
    *,
    index: int = 1,
    components: list[ComponentSpec] | None = None,
) -> TemplateManifest:
    """Манифест с одним слайдом-примером. Макет — второй, с телом контента: первый
    у синтетического манифеста титульный, и структурное правило забрало бы пример себе."""
    example = TemplateExample(
        slide_index=index,
        layout_id=manifest.layouts[-1].layout_id,
        part_name=f"ppt/slides/slide{index}.xml",
        shapes=shapes,
    )
    return manifest.model_copy(update={"examples": [example], "components": components or []})


def only(manifest: TemplateManifest):
    ds = derive(manifest)
    assert len(ds.recipes) == 1, f"ожидался один рецепт, получено {len(ds.recipes)}"
    return ds.recipes[0]


# --- вид рецепта ---------------------------------------------------------------


def test_the_capacity_of_a_zone_is_counted_as_the_capacity_of_a_placeholder() -> None:
    """Вместимость зоны и плейсхолдера обязаны мериться одинаково: иначе у композиции
    два разных лимита на одно и то же место. Слой ниже `parsing`, поэтому величины
    продублированы — этот тест и держит их вместе."""
    from deckforge.parsing.capacity import _AVG_CHAR_WIDTH_RATIO, _LINE_HEIGHT_RATIO

    assert CHAR_WIDTH_RATIO == _AVG_CHAR_WIDTH_RATIO
    assert LINE_HEIGHT_RATIO == _LINE_HEIGHT_RATIO


def test_an_example_with_a_row_of_repeats_is_a_cards_recipe(manifest: TemplateManifest) -> None:
    """Повтор — ячейка компонента шаблона: три плашки в ряд с равным шагом."""
    width = manifest.slide_size.cx_emu
    cell = width // 5
    step = width // 4
    cards = [
        shape(f"c{i}", x=step * i, y=4_000_000, cx=cell, cy=1_000_000, kind=ShapeKind.SHAPE)
        for i in range(3)
    ]
    texts = [
        shape(f"t{i}", x=step * i, y=4_200_000, cx=cell, cy=400_000, xml_id=100 + i)
        for i in range(3)
    ]
    title = shape("title", x=600_000, y=400_000, cx=width - 1_200_000, cy=900_000, size_pt=40.0)
    tile = ComponentSpec(
        kind=ComponentKind.TILE,
        repeats=3,
        axis="row",
        width_share=cell / width,
        height_share=1_000_000 / manifest.slide_size.cy_emu,
        gap_share=step / width,
        seen_on=[1],
    )

    recipe = only(with_example(manifest, [title, *cards, *texts], components=[tile]))

    assert recipe.kind is RecipeKind.CARDS
    assert recipe.repeats == 3
    assert {zone.repeat for zone in recipe.zones if zone.repeat is not None} == {0, 1, 2}


def test_a_row_with_a_big_number_is_a_metrics_recipe(manifest: TemplateManifest) -> None:
    """Нарушитель к предыдущему: тот же ряд, но с крупным коротким числом на плашке."""
    width = manifest.slide_size.cx_emu
    cell, step = width // 5, width // 4
    cards = [
        shape(f"c{i}", x=step * i, y=4_000_000, cx=cell, cy=1_000_000, kind=ShapeKind.SHAPE)
        for i in range(3)
    ]
    numbers = [
        shape(f"n{i}", x=step * i, y=4_100_000, cx=cell, cy=600_000, text_len=4, size_pt=40.0)
        for i in range(3)
    ]
    title = shape("title", x=600_000, y=400_000, cx=width - 1_200_000, cy=900_000, size_pt=40.0)
    tile = ComponentSpec(
        kind=ComponentKind.TILE,
        repeats=3,
        axis="row",
        width_share=cell / width,
        height_share=1_000_000 / manifest.slide_size.cy_emu,
        gap_share=step / width,
        seen_on=[1],
    )

    recipe = only(with_example(manifest, [title, *cards, *numbers], components=[tile]))

    assert recipe.kind is RecipeKind.METRICS


def test_a_big_picture_in_the_content_area_makes_a_picture_recipe(
    manifest: TemplateManifest,
) -> None:
    width, height = manifest.slide_size.cx_emu, manifest.slide_size.cy_emu
    picture = shape(
        "pic",
        x=width // 2,
        y=height // 4,
        cx=width // 2,
        cy=(height * 2) // 3,
        kind=ShapeKind.PICTURE,
        text_len=0,
        size_pt=None,
    )
    title = shape("title", x=600_000, y=400_000, cx=width // 2, cy=900_000, size_pt=40.0)
    body = shape("body", x=600_000, y=2_000_000, cx=width // 3, cy=2_000_000)

    recipe = only(with_example(manifest, [title, body, picture]))

    assert recipe.kind is RecipeKind.TEXT_WITH_PICTURE
    assert recipe.has_picture is True


def test_a_small_picture_does_not_make_a_picture_recipe(manifest: TemplateManifest) -> None:
    """Норма: логотип в углу — не «текст с картинкой», иначе им станет каждый пример."""
    width = manifest.slide_size.cx_emu
    logo = shape(
        "logo",
        x=600_000,
        y=600_000,
        cx=400_000,
        cy=300_000,
        kind=ShapeKind.PICTURE,
        text_len=0,
        size_pt=None,
    )
    title = shape("title", x=600_000, y=1_400_000, cx=width // 2, cy=900_000, size_pt=40.0)
    body = shape("body", x=600_000, y=3_000_000, cx=width // 2, cy=2_000_000)

    recipe = only(with_example(manifest, [title, body, logo]))

    assert recipe.kind is RecipeKind.TEXT
    assert recipe.has_picture is False


def test_an_example_with_a_chart_is_not_a_recipe(manifest: TemplateManifest) -> None:
    """Сужение v1: диаграмму колода строит своими данными, а не текстом в чужую рамку."""
    width = manifest.slide_size.cx_emu
    chart = shape(
        "chart",
        x=600_000,
        y=2_000_000,
        cx=width // 2,
        cy=2_000_000,
        kind=ShapeKind.CHART,
        text_len=0,
        size_pt=None,
    )
    title = shape("title", x=600_000, y=400_000, cx=width // 2, cy=900_000, size_pt=40.0)

    assert derive(with_example(manifest, [title, chart])).recipes == []


def test_a_lonely_zone_is_not_a_recipe(manifest: TemplateManifest) -> None:
    """Нарушитель: одна подпись на пустом слайде — это не композиция."""
    caption = shape("only", x=600_000, y=5_000_000, cx=1_200_000, cy=300_000, size_pt=12.0)

    assert derive(with_example(manifest, [caption])).recipes == []


# --- зоны ----------------------------------------------------------------------


def test_every_recipe_has_a_title_zone_and_addressable_zones(
    manifest: TemplateManifest,
) -> None:
    """Заголовок вёрстка не удаляет никогда — значит он обязан быть найден."""
    width = manifest.slide_size.cx_emu
    title = shape("t", x=600_000, y=400_000, cx=width // 2, cy=900_000, size_pt=40.0, xml_id=7)
    body = shape("b", x=600_000, y=3_000_000, cx=width // 2, cy=2_000_000, xml_id=8)

    recipe = only(with_example(manifest, [title, body]))

    assert recipe.recipe_id == "ex001"
    assert recipe.part_name == "ppt/slides/slide1.xml"
    assert [zone.zone_id for zone in recipe.zones] == ["z7", "z8"]
    assert any(zone.role is TypeLevel.SLIDE_TITLE for zone in recipe.zones)
    assert all(zone.capacity_chars > 0 for zone in recipe.zones)


def test_a_cold_manifest_without_examples_has_no_recipes(manifest: TemplateManifest) -> None:
    ds = derive(manifest)

    assert manifest.examples == []
    assert ds.recipes == []


def test_the_plan_order_maps_to_the_kind_of_a_recipe() -> None:
    """Одна таблица на все шаблоны: её читают меню плана (05a) и подбор (05b)."""
    assert kind_for_visual("kpi") is RecipeKind.METRICS
    assert kind_for_visual("image") is RecipeKind.TEXT_WITH_PICTURE
    assert kind_for_visual("callout:risk") is None
    assert kind_for_visual(None) is None


# --- на настоящих шаблонах -----------------------------------------------------


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_a_case_template_gives_a_catalogue_of_compositions(name: str) -> None:
    parsed = TemplateParser().parse(case_template(name), use_cache=False)

    ds = derive(parsed)

    assert ds.recipes, f"{name}: рецептов нет, хотя примеры в шаблоне есть"
    for recipe in ds.recipes:
        assert recipe.zones, f"{recipe.recipe_id}: рецепт без зон"
        assert any(zone.role is TypeLevel.SLIDE_TITLE for zone in recipe.zones)
        assert len({zone.zone_id for zone in recipe.zones}) == len(recipe.zones)
        assert all(zone.capacity_chars >= 0 for zone in recipe.zones)
        assert recipe.recipe_id == f"ex{recipe.example_index:03d}"
    assert derive(parsed).recipes == ds.recipes, "второй вызов дал другой каталог"


@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_the_catalogue_of_a_case_template_is_not_one_single_kind(name: str) -> None:
    """Каталог из одного вида означает, что вид не выводится, а назначается."""
    parsed = TemplateParser().parse(case_template(name), use_cache=False)

    kinds = {recipe.kind for recipe in derive(parsed).recipes}

    assert len(kinds) > 1, f"{name}: все рецепты одного вида — {kinds}"
