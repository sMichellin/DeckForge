"""Заголовок — всегда текст, а пример из чисел не достаётся прозе (К2, К4).

Change `a-title-is-never-a-number`.

План Б, круг 2, корни К2 и К4. Сценарии — из дельты
`openspec/changes/a-title-is-never-a-number/specs/slide-composition/`.

Паспорт метил место числом по одному признаку — «держит меньше двух слов». Числом
становились заголовки на 8–16 знаков (обложка WorkSpace, `ex003`, `ex024`), и модель,
у которой в фактах чисел нет, писала в них «1»: колода открывалась единицей вместо
названия (прогон 29.09, 19 находок `content.numbers_grounded`).

Замер здесь — подделка `fits` по длине текста, как в тесте паспорта: модульный тест
не зависит от шрифтов образа. Последний тест — на сохранённых прогонах 28.09.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.composition.assign import assign_recipes
from deckforge.composition.passport import Fits, build_passport, with_passports
from deckforge.designsystem.models import (
    DesignSystem,
    GridSpec,
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
from deckforge.domain.template import ExampleShape, Margins, ShapeKind, TemplateExample
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.replay import from_fixture

CM = 360_000
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-28"
SLIDE_AREA = 12_000_000 * 6_750_000


def shape(xml_id: int, y: float, cy: float, *, z: int, text: int = 0) -> ExampleShape:
    return ExampleShape(
        shape_id=f"s{xml_id}",
        kind=ShapeKind.TEXT if text else ShapeKind.SHAPE,
        x=CM, y=int(y * CM), cx=20 * CM, cy=int(cy * CM), z=z, xml_id=xml_id, text_len=text,
    )


def zone_of(item: ExampleShape, role: TypeLevel) -> Zone:
    return Zone(
        zone_id=f"z{item.xml_id}", xml_id=item.xml_id, role=role, capacity_chars=100,
        size_pt=12.0, x=item.x, y=item.y, cx=item.cx, cy=item.cy,
    )


def limits(caps: dict[str, int]) -> Fits:
    """Подделка замера: текст встаёт в зону, пока не длиннее её лимита."""

    def fits(recipe: Recipe, texts: dict[str, str]) -> dict[str, bool]:
        return {zone_id: len(text) <= caps.get(zone_id, 0) for zone_id, text in texts.items()}

    return fits


def two_places(
    kind: RecipeKind, top: TypeLevel, bottom: TypeLevel
) -> tuple[Recipe, TemplateExample]:
    """Пример из двух мест: тесное сверху и просторное снизу."""
    head = shape(100, 0.5, 1.2, z=50, text=10)
    body = shape(101, 3.0, 4.0, z=40, text=80)
    recipe = Recipe(
        recipe_id="ex001", example_index=1, kind=kind,
        zones=[zone_of(head, top), zone_of(body, bottom)],
        layout_name="Контент",
    )
    return recipe, TemplateExample(slide_index=1, layout_id="L07", shapes=[head, body])


def passport_of(recipe: Recipe, example: TemplateExample, caps: dict[str, int]):
    made = build_passport(recipe, example, limits(caps), slide_area=SLIDE_AREA)
    assert not isinstance(made, str), made
    return made


# --- место заголовка --------------------------------------------------------------


def test_a_tiny_title_place_is_still_text() -> None:
    """Нарушитель: место заголовка на восемь знаков числом не становится."""
    recipe, example = two_places(RecipeKind.TEXT, TypeLevel.SLIDE_TITLE, TypeLevel.BODY)

    card = passport_of(recipe, example, {"z100": 8, "z101": 90})

    title = next(place for place in card.places if place.zone_id == "z100")
    assert title.kind is PlaceKind.TEXT, "заголовок утверждён планировщиком и числом не бывает"
    assert title.role is TypeLevel.SLIDE_TITLE
    assert title.capacity_chars > 0


def test_a_tiny_caption_is_still_a_number() -> None:
    """Норма: тесное место не-заголовка по-прежнему место под число или метку."""
    recipe, example = two_places(RecipeKind.TEXT, TypeLevel.CAPTION, TypeLevel.BODY)

    card = passport_of(recipe, example, {"z100": 8, "z101": 90})

    assert next(place for place in card.places if place.zone_id == "z100").kind is PlaceKind.NUMBER


def test_display_is_a_title_on_the_cover() -> None:
    """Норма: на обложке крупная строка — заголовок, а не число."""
    recipe, example = two_places(RecipeKind.COVER, TypeLevel.DISPLAY, TypeLevel.BODY)

    card = passport_of(recipe, example, {"z100": 8, "z101": 90})

    assert next(place for place in card.places if place.zone_id == "z100").kind is PlaceKind.TEXT


def test_display_outside_the_cover_is_a_number() -> None:
    """Нарушитель: крупная строка на плитке показателей — число, и текстом не становится."""
    recipe, example = two_places(RecipeKind.METRICS, TypeLevel.DISPLAY, TypeLevel.BODY)

    card = passport_of(recipe, example, {"z100": 8, "z101": 90})

    assert next(place for place in card.places if place.zone_id == "z100").kind is PlaceKind.NUMBER


# --- пример из чисел и подписей ---------------------------------------------------


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


def scaled(recipe_id: str, kind: RecipeKind, caps: dict[str, int]) -> Recipe:
    """Пример с заданными ёмкостями мест: так отличается шкала Ганта от карточек."""
    head = shape(100, 0.5, 1.2, z=50, text=10)
    made = [head]
    zones = [zone_of(head, TypeLevel.SLIDE_TITLE)]
    for index, _cap in enumerate(sorted(key for key in caps if key != "z100")):
        item = shape(200 + index, 3.0 + index, 0.8, z=40 + index, text=12)
        made.append(item)
        zones.append(zone_of(item, TypeLevel.CAPTION))
    recipe = Recipe(
        recipe_id=recipe_id, example_index=int(recipe_id[2:]), kind=kind, zones=zones,
        layout_name="Контент",
    )
    example = TemplateExample(slide_index=int(recipe_id[2:]), layout_id="L07", shapes=made)
    mapping = {f"z{item.xml_id}": caps[key] for item, key in zip(
        made, ["z100", *sorted(key for key in caps if key != "z100")], strict=True)}
    return recipe.model_copy(
        update={"passport": passport_of(recipe, example, mapping)}
    )


def deck(*slides: SlidePlan) -> DeckPlan:
    return DeckPlan(deck_id="d1", variant="A", seed=1341, slides=list(slides))


def prose_slide(slide_id: str = "s02") -> SlidePlan:
    return SlidePlan(
        slide_id=slide_id, intent=SlideIntent.EVIDENCE, headline="Вывод слайда",
        fact_refs=["f001"],
    )


def test_an_example_of_labels_is_not_given_to_prose() -> None:
    """Нарушитель: у примера больше половины мест — подписи в пару слов, прозе он не даётся.

    Это `ex052` VK Tech: каталог назвал диаграмму Ганта видом «text», и абзац разрезался
    по подписям полос.
    """
    gantt = scaled("ex052", RecipeKind.TEXT, {"z100": 40, "a": 6, "b": 6, "c": 6, "d": 6})
    prose = scaled("ex009", RecipeKind.TEXT, {"z100": 40, "a": 90, "b": 90})

    out = assign_recipes(deck(prose_slide()), design_system(gantt, prose), seed=1341)

    assert out[0].recipe_id == "ex009"


def test_prose_has_no_example_rather_than_a_scale() -> None:
    """Нарушитель: другого примера нет — слайд идёт дизайн-системой, а не в подписи шкалы."""
    gantt = scaled("ex052", RecipeKind.TEXT, {"z100": 40, "a": 6, "b": 6, "c": 6, "d": 6})

    out = assign_recipes(deck(prose_slide()), design_system(gantt), seed=1341)

    assert out[0].recipe_id is None


def test_a_metrics_slide_still_gets_its_numbers() -> None:
    """Норма: слайд, заказавший показатели, берёт пример с местами-числами законно."""
    tiles = scaled("ex019", RecipeKind.METRICS, {"z100": 40, "a": 6, "b": 6, "c": 6, "d": 6})
    slide = SlidePlan(
        slide_id="s03", intent=SlideIntent.EVIDENCE, headline="Итоги квартала",
        fact_refs=["f001", "f002"], suggested_visual="kpi",
    )

    out = assign_recipes(deck(slide), design_system(tiles), seed=1341)

    assert out[0].recipe_id == "ex019"


def test_a_structural_slide_keeps_its_short_example() -> None:
    """Норма: раздел несёт заголовок, а не абзац — короткие места ему нормальны."""
    section = scaled("ex016", RecipeKind.SECTION, {"z100": 40, "a": 6})
    slide = SlidePlan(
        slide_id="s05", intent=SlideIntent.SECTION, headline="Часть вторая", fact_refs=[],
    )

    out = assign_recipes(deck(slide), design_system(section), seed=1341)

    assert out[0].recipe_id == "ex016"


# --- мерило на сохранённых прогонах -----------------------------------------------


@pytest.mark.parametrize(
    ("name", "with_example"), [("education", 5), ("vk-tech", 4), ("workspace", 8)]
)
def test_no_title_place_is_a_number_and_row_one_holds(name: str, with_example: int) -> None:
    """Мерило change на прогонах 28.09: заголовков-чисел нет, а слайдов с примером не меньше.

    «До»: мест ступени `slide_title` с видом «число» — 4 у WorkSpace, 9 у Education,
    0 у VK Tech; **содержательных** слайдов с примером — 8, 4 и 5. Правило «пример
    не для прозы» снимает `ex052` (шкала Ганта) и `ex027` (номера карточек)
    с содержательных слайдов VK Tech, и на их место встают примеры с местами под прозу —
    число слайдов с примером то же.

    Считаются содержательные слайды: строка 1 приёмки — про них. Структурные с круга 2
    отбираются по местам (`the-cover-holds-its-facts`), и их счёт живёт в тесте того change.
    """
    run = from_fixture(FIXTURES / name)
    ds, _report = with_passports(run.design_system, run.manifest, FontLibrary.default())

    numbered = [
        (recipe.recipe_id, place.place_id)
        for recipe in ds.recipes
        if recipe.passport is not None
        for place in recipe.passport.places
        if place.role is TypeLevel.SLIDE_TITLE and place.kind is PlaceKind.NUMBER
    ]
    out = assign_recipes(run.plan, ds, seed=run.plan.seed)

    structural = {"title", "section", "closing"}
    intents = {slide.slide_id: slide.intent.value for slide in run.plan.slides}
    content = [item for item in out if intents[item.slide_id] not in structural]

    assert numbered == [], "место заголовка слайда числом не бывает"
    assert sum(1 for item in content if item.recipe_id) == with_example, "строка 1 не просела"
