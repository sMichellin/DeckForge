"""Предел схемы — с запасом, настоящий предел — в промпте. Change `the-limit-is-not-a-guillotine`.

План Б, круг 2, корень К1. Сценарии — из дельты
`openspec/changes/the-limit-is-not-a-guillotine/specs/slide-composition/`.

Прогон 29.09 отдал семь текстов длиной ровно в ёмкость места, пять из них оборваны посреди
слова: грамматика llama.cpp держит `maxLength` знаками и обрывает генерацию на знаке.
Замер вписывания обрубок не ловит — он короче места и честно «встаёт», поэтому здесь
проверяется и то, что текст, упёршийся в потолок схемы, зовёт повтор **вопреки** замеру.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deckforge.composition.assign import RecipeAssignment
from deckforge.composition.composer import PLACES_PROMPT_VERSION, SlideComposer
from deckforge.composition.places import (
    SLACK,
    at_the_ceiling,
    blocks_for_places,
    ceiling,
    longest_word,
    response_schema,
)
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
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.enums import SlideIntent, TextRole
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import TextBlock
from deckforge.domain.template import Margins, TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import Completion
from deckforge.registry import get_prompt_registry, load_variant_profiles

EMU_PER_CM = 360_000


def place(place_id: str, zone_id: str, role: TypeLevel, chars: int) -> Place:
    return Place(
        place_id=place_id, kind=PlaceKind.TEXT, zone_id=zone_id, role=role, capacity_chars=chars
    )


def passport_of(*places: Place, row: tuple[Place, ...] = ()) -> ExamplePassport:
    groups = [PlaceGroup(group_id=f"g{index:02d}", places=[item])
              for index, item in enumerate(places, start=1)]
    groups += [
        PlaceGroup(group_id=f"g{len(places) + index:02d}", places=[item], row="r1")
        for index, item in enumerate(row, start=1)
    ]
    return ExamplePassport(groups=groups)


def roomy_zone(zone_id: str, role: TypeLevel) -> Zone:
    """Зона с просторной рамкой: по замеру в неё встаёт и текст длиннее ёмкости паспорта.

    Ровно тот случай, ради которого К1 и заведён: ёмкость посчитана знаками, рамка держит
    больше, замер говорит «встал» — и обрубок уезжает в колоду незамеченным.
    """
    return Zone(
        zone_id=zone_id,
        role=role,
        capacity_chars=20,
        size_pt=12,
        x=EMU_PER_CM,
        y=EMU_PER_CM if role is TypeLevel.SLIDE_TITLE else 6 * EMU_PER_CM,
        cx=24 * EMU_PER_CM,
        cy=3 * EMU_PER_CM,
    )


def design_system(*recipes: Recipe) -> DesignSystem:
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


# --- потолок схемы ----------------------------------------------------------------


def test_the_ceiling_is_wider_than_the_place() -> None:
    """Норма: потолок схемы — полторы ёмкости, а не ёмкость."""
    assert ceiling(40) == round(40 * SLACK) == 60
    assert ceiling(40) > 40


def test_a_tight_place_gets_room_for_the_longest_word() -> None:
    """Нарушитель: у места на три знака полтора не дают и слова — считаем словом."""
    assert ceiling(3) < len("презентаций")
    assert ceiling(3, len("презентаций")) == 3 + len("презентаций") == 14


def test_the_longest_word_comes_from_the_slide_material() -> None:
    """Норма: запас меряется словами заголовка и фактов этого слайда."""
    assert longest_word(["Рост выручки", "Автоматизация согласований"]) == len("Автоматизация")
    assert longest_word([]) == 0


def test_the_schema_gives_every_place_its_ceiling() -> None:
    """Норма: потолок стоит у каждого места, в том числе у мест ряда, и одинаков в ряду."""
    card = passport_of(
        place("p01", "z01", TypeLevel.SLIDE_TITLE, 60),
        place("p02", "z02", TypeLevel.BODY, 3),
        row=(place("p03", "z03", TypeLevel.CARD_TITLE, 24),
             place("p04", "z04", TypeLevel.CARD_TITLE, 24)),
    )

    schema = response_schema(card, {"r1": 2}, longest=11)

    assert schema["properties"]["p01"]["maxLength"] == ceiling(60, 11)
    assert schema["properties"]["p02"]["maxLength"] == ceiling(3, 11) == 14
    assert schema["properties"]["r1"]["items"]["properties"]["t1"]["maxLength"] == ceiling(24, 11)


# --- текст, упёршийся в потолок ----------------------------------------------------


def test_text_at_the_ceiling_is_treated_as_cut_off() -> None:
    """Нарушитель: длина ровно в потолок — обрыв грамматики, а не выбор модели."""
    card = passport_of(place("p01", "z01", TypeLevel.SLIDE_TITLE, 20))
    schema = response_schema(card, {}, longest=0)
    top = schema["properties"]["p01"]["maxLength"]
    blocks = [TextBlock(block_id="b01", role=TextRole.TITLE, text="ы" * top, zone_id="z01")]

    assert at_the_ceiling(card, {}, blocks, schema) == {"z01": 20}


def test_text_below_the_ceiling_is_not_cut_off() -> None:
    """Норма: текст короче потолка оборванным не считается, даже если он длиной в ёмкость."""
    card = passport_of(place("p01", "z01", TypeLevel.SLIDE_TITLE, 6))
    schema = response_schema(card, {}, longest=0)
    blocks = [TextBlock(block_id="b01", role=TextRole.TITLE, text="минуты", zone_id="z01")]

    assert len("минуты") == 6, "ровно ёмкость места — прежде это звало лишний повтор"
    assert at_the_ceiling(card, {}, blocks, schema) == {}


def test_the_row_places_are_checked_too() -> None:
    """Нарушитель: место ряда, упёршееся в потолок, названо своей ёмкостью."""
    card = passport_of(
        place("p01", "z01", TypeLevel.SLIDE_TITLE, 30),
        row=(place("p02", "z02", TypeLevel.CARD_TITLE, 10),),
    )
    schema = response_schema(card, {"r1": 1}, longest=0)
    top = schema["properties"]["r1"]["items"]["properties"]["t1"]["maxLength"]
    answer = {"p01": "Вывод", "r1": [{"t1": "ы" * top}]}
    blocks = blocks_for_places(card, {"r1": 1}, answer)

    assert at_the_ceiling(card, {"r1": 1}, blocks, schema) == {"z02": 10}


# --- промпт -----------------------------------------------------------------------


def test_the_prompt_names_the_place_limit_not_the_schema_ceiling() -> None:
    """Норма: модель узнаёт настоящий предел из промпта, а не из формата ответа."""
    bundle = get_prompt_registry().load("slide_composer", version=PLACES_PROMPT_VERSION)

    assert PLACES_PROMPT_VERSION != "2.0.0", "версия поднята: на 2.0.0 есть прогон 29.09"
    _system, user = bundle.render(
        slide=plan_slide(),
        facts=[Fact(fact_id="f001", text="Выручка выросла на 37,5 %")],
        recipe_kind=RecipeKind.CARDS.value,
        variant="A",
        seed=1341,
        language="ru",
        brief=brief(),
        no_think=False,
        single_places=[{"place_id": "p01", "role": "slide_title", "chars": 20, "number": False}],
        place_rows=[],
    )

    assert "до 20 знаков" in user, "предел места назван промптом"
    assert "запас" in user


# --- слайд целиком ----------------------------------------------------------------


class FakeLlm:
    model = "fake"

    def __init__(self, *payloads: dict[str, Any]) -> None:
        self.payloads = list(payloads)
        self.asked: list[dict[str, Any]] = []

    def complete(self, messages: list[dict[str, Any]], **kw: Any) -> Completion:
        self.asked.append({"messages": messages, **kw})
        payload = self.payloads[min(len(self.asked) - 1, len(self.payloads) - 1)]
        return Completion(text=json.dumps(payload, ensure_ascii=False), model=self.model)


def brief() -> Brief:
    return Brief(purpose="product", audience="правление", target_slides=6, language="ru")


def content() -> ContentPackage:
    return ContentPackage(
        brief=brief(),
        facts=[Fact(fact_id="f001", text="Автоматизация согласований сократила срок на 37,5 %")],
    )


def plan_slide() -> SlidePlan:
    return SlidePlan(
        slide_id="s03",
        intent=SlideIntent.EVIDENCE,
        headline="Выручка выросла",
        fact_refs=["f001"],
        suggested_visual=None,
    )


def roomy_recipe() -> tuple[Recipe, ExamplePassport]:
    card = passport_of(
        place("p01", "z01", TypeLevel.SLIDE_TITLE, 20),
        place("p02", "z02", TypeLevel.BODY, 20),
    )
    return (
        Recipe(
            recipe_id="ex001",
            example_index=1,
            kind=RecipeKind.TEXT,
            zones=[roomy_zone("z01", TypeLevel.SLIDE_TITLE), roomy_zone("z02", TypeLevel.BODY)],
            passport=card,
            layout_name="Контент",
        ),
        card,
    )


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


@pytest.mark.asyncio
async def test_a_text_at_the_ceiling_asks_again_even_though_it_fits(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Нарушитель: обрубок «встал» по замеру — повтор всё равно зовётся, с пределом места."""
    recipe, card = roomy_recipe()
    top = response_schema(card, {}, longest=longest_word(
        ["Выручка выросла", "Автоматизация согласований сократила срок на 37,5 %"]
    ))["properties"]["p01"]["maxLength"]
    llm = FakeLlm(
        {"p01": "Автоматизация согласований сократила срок вдвое и дальше"[:top], "p02": "Кратко"},
        {"p01": "Срок согласований −37,5 %", "p02": "Коротко"},
    )
    composer = SlideComposer(llm)

    composed = await composer.compose(
        plan_slide(),
        content(),
        manifest,
        variant_a,
        1341,
        design_system=design_system(recipe),
        assignment=RecipeAssignment(slide_id="s03", recipe_id="ex001", reason="вид text"),
    )

    assert len(llm.asked) == 2, "упёрся в потолок — переспрашиваем, что бы ни сказал замер"
    assert "p01 — до 20 знаков" in llm.asked[1]["messages"][-1]["content"]
    assert any("упёрся в предел схемы" in note for note in composer.notes)
    title = composed.block("b01")
    assert title is not None and isinstance(title, TextBlock)
    assert title.text == "Срок согласований −37,5 %"


@pytest.mark.asyncio
async def test_a_text_below_the_ceiling_asks_nothing(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма: текст короче потолка и вставший по замеру повтора не зовёт."""
    recipe, _card = roomy_recipe()
    llm = FakeLlm({"p01": "Выручка выросла", "p02": "Подписки и услуги"})
    composer = SlideComposer(llm)

    await composer.compose(
        plan_slide(),
        content(),
        manifest,
        variant_a,
        1341,
        design_system=design_system(recipe),
        assignment=RecipeAssignment(slide_id="s03", recipe_id="ex001", reason="вид text"),
    )

    assert len(llm.asked) == 1
    assert composer.notes == []


@pytest.mark.asyncio
async def test_a_stubborn_model_gets_its_text_trimmed_by_words(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма: повтор не помог — обрезка по словам, а не по знакам, и с заметкой."""
    recipe, card = roomy_recipe()
    longest = longest_word(
        ["Выручка выросла", "Автоматизация согласований сократила срок на 37,5 %"]
    )
    top = response_schema(card, {}, longest=longest)["properties"]["p01"]["maxLength"]
    stuck = "Автоматизация согласований сократила срок вдвое и дальше"[:top]
    llm = FakeLlm({"p01": stuck, "p02": "Коротко"})
    composer = SlideComposer(llm)

    composed = await composer.compose(
        plan_slide(),
        content(),
        manifest,
        variant_a,
        1341,
        design_system=design_system(recipe),
        assignment=RecipeAssignment(slide_id="s03", recipe_id="ex001", reason="вид text"),
    )

    title = composed.block("b01")
    assert title is not None and isinstance(title, TextBlock)
    assert len(title.text) <= 20, "обрезано под настоящий предел места"
    assert stuck.startswith(title.text)
    assert stuck[len(title.text) : len(title.text) + 1] in (" ", ""), "обрыв по границе слова"
    assert any("обрезан по словам под место" in note for note in composer.notes)
