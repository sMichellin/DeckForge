"""Число берётся из фактов, номер карточки ставит код. Change `numbers-come-from-facts`.

План Б, круг 2, корень К2. Сценарии — из дельты
`openspec/changes/numbers-come-from-facts/specs/slide-composition/`.

Прогон 29.09 дал 19 находок `content.numbers_grounded` — «1» на обложке WorkSpace,
«2 задачи», «1 сервис», «100 %», «0 ошибок», «10x». Все 24 заполнения мест-чисел
пришлись на слайды, где в фактах не было ни одной цифры: место просило число, а взять
его было неоткуда. Здесь проверяется, что такое место у модели не спрашивается вовсе.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deckforge.composition.assign import RecipeAssignment
from deckforge.composition.composer import PLACES_PROMPT_VERSION, SlideComposer
from deckforge.composition.places import (
    ORDINAL_CHARS,
    asked_places,
    blocks_for_places,
    has_numbers,
    ordinals,
    places_brief,
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
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import Margins, TemplateManifest
from deckforge.domain.variants import VariantProfile
from deckforge.inference.client import Completion
from deckforge.registry import get_prompt_registry, load_variant_profiles

EMU_PER_CM = 360_000


def place(place_id: str, zone_id: str, role: TypeLevel, chars: int, kind: PlaceKind) -> Place:
    return Place(
        place_id=place_id, kind=kind, zone_id=zone_id, role=role, capacity_chars=chars
    )


def text_place(place_id: str, zone_id: str, role: TypeLevel, chars: int = 90) -> Place:
    return place(place_id, zone_id, role, chars, PlaceKind.TEXT)


def number_place(place_id: str, zone_id: str, chars: int) -> Place:
    return place(place_id, zone_id, TypeLevel.DISPLAY, chars, PlaceKind.NUMBER)


def tile_passport(number_chars: int = 9) -> ExamplePassport:
    """Заголовок, крупное число и подпись под ним — плитка показателя."""
    return ExamplePassport(
        groups=[
            PlaceGroup(group_id="g01", places=[text_place("p01", "z01", TypeLevel.SLIDE_TITLE)]),
            PlaceGroup(group_id="g02", places=[number_place("p02", "z02", number_chars)]),
            PlaceGroup(group_id="g03", places=[text_place("p03", "z03", TypeLevel.CAPTION, 40)]),
        ]
    )


def numbered_row(cards: int = 3, number_chars: int = 2) -> ExamplePassport:
    """Ряд пронумерованных карточек: номер и текст в каждой."""
    groups = [
        PlaceGroup(group_id="g01", places=[text_place("p01", "z01", TypeLevel.SLIDE_TITLE)])
    ]
    for index in range(cards):
        number = index * 2 + 2
        groups.append(
            PlaceGroup(
                group_id=f"g{index + 2:02d}",
                row="r1",
                places=[
                    number_place(f"p{number:02d}", f"z{number:02d}", number_chars),
                    text_place(f"p{number + 1:02d}", f"z{number + 1:02d}", TypeLevel.BODY, 60),
                ],
            )
        )
    return ExamplePassport(groups=groups)


# --- место-число без чисел в фактах -----------------------------------------------


def test_the_material_of_the_slide_decides() -> None:
    """Норма: цифра где угодно в материале — это «есть откуда взять число»."""
    assert has_numbers(["Выручка выросла на 37,5 %"])
    assert has_numbers(["Итоги 2026 года"])
    assert not has_numbers(["Автоматизация согласований", "Ручной труд уходит"])


def test_a_number_place_is_not_asked_without_numbers() -> None:
    """Нарушитель: в материале слайда нет цифр — места-числа у модели не спрашиваются."""
    card = tile_passport()

    asked = asked_places(card, {}, numbers=False)

    assert asked == {"p01", "p03"}, "текстовые места остаются, место-число уходит"
    schema = response_schema(card, {}, asked=asked)
    assert "p02" not in schema["properties"]
    assert sorted(schema["required"]) == ["p01", "p03"]
    brief = places_brief(card, {}, asked)
    assert [item["place_id"] for item in brief["single_places"]] == ["p01", "p03"]


def test_a_number_place_is_asked_when_the_slide_has_numbers() -> None:
    """Норма: число в фактах есть — место-число заказывается как прежде."""
    card = tile_passport()

    asked = asked_places(card, {}, numbers=True)

    assert asked == {"p01", "p02", "p03"}
    assert "p02" in response_schema(card, {}, asked=asked)["properties"]


def test_a_row_without_asked_cells_leaves_the_schema() -> None:
    """Нарушитель: ряд, где все места — числа без чисел в фактах, в схему не идёт."""
    card = ExamplePassport(
        groups=[
            PlaceGroup(group_id="g01", places=[text_place("p01", "z01", TypeLevel.SLIDE_TITLE)]),
            PlaceGroup(group_id="g02", row="r1", places=[number_place("p02", "z02", 9)]),
            PlaceGroup(group_id="g03", row="r1", places=[number_place("p03", "z03", 9)]),
        ]
    )

    schema = response_schema(card, {"r1": 2}, asked=asked_places(card, {"r1": 2}, numbers=False))

    assert "r1" not in schema["properties"]
    assert schema["required"] == ["p01"]


# --- номер карточки ---------------------------------------------------------------


def test_the_card_number_is_written_by_code() -> None:
    """Нарушитель: номер карточки модель не получает — его ставит код по порядку ряда."""
    card = numbered_row(cards=3)

    numbers = ordinals(card, {"r1": 3})

    assert numbers == {"p02": "01", "p04": "02", "p06": "03"}
    asked = asked_places(card, {"r1": 3}, numbers=True)
    assert asked == {"p01", "p03", "p05", "p07"}, "числа ряда не спрашиваются даже при фактах"
    cells = response_schema(card, {"r1": 3}, asked=asked)["properties"]["r1"]["items"]
    assert list(cells["properties"]) == ["t2"], "у модели остаётся только текст карточки"


def test_the_code_number_lands_in_its_place() -> None:
    """Норма: номер встаёт в своё место, текст карточки — в своё, порядок чтения цел."""
    card = numbered_row(cards=2)
    answer = {"p01": "Как это работает", "r1": [{"t2": "Собираем материал"}, {"t2": "Верстаем"}]}

    blocks = blocks_for_places(card, {"r1": 2}, answer, ordinals(card, {"r1": 2}))

    assert [(block.zone_id, block.text) for block in blocks] == [
        ("z01", "Как это работает"),
        ("z02", "01"),
        ("z03", "Собираем материал"),
        ("z04", "02"),
        ("z05", "Верстаем"),
    ]


def test_a_wide_number_place_is_not_a_card_number() -> None:
    """Норма: показатель шире трёх знаков номером не считается — его пишет модель."""
    card = numbered_row(cards=2, number_chars=ORDINAL_CHARS + 3)

    assert ordinals(card, {"r1": 2}) == {}
    assert "p02" in asked_places(card, {"r1": 2}, numbers=True)


def test_a_one_digit_place_gets_a_number_without_a_leading_zero() -> None:
    """Норма: место на один знак держит «1», а не «01»."""
    card = numbered_row(cards=2, number_chars=1)

    assert ordinals(card, {"r1": 2}) == {"p02": "1", "p04": "2"}


# --- промпт -----------------------------------------------------------------------


def test_the_prompt_does_not_carry_the_seed() -> None:
    """Нарушитель: номер прогона в тексте промпта — это «1341» крупно на слайде."""
    bundle = get_prompt_registry().load("slide_composer", version=PLACES_PROMPT_VERSION)
    system, user = bundle.render(
        slide=plan_slide(),
        facts=[Fact(fact_id="f001", text="Согласование стало быстрее")],
        recipe_kind=RecipeKind.CARDS.value,
        variant="A",
        seed=1341,
        language="ru",
        brief=brief(),
        no_think=False,
        single_places=[{"place_id": "p01", "role": "slide_title", "chars": 40, "number": False}],
        place_rows=[],
    )

    assert "1341" not in user and "1341" not in system
    assert "Seed" not in user and "seed" not in user
    assert "не повод число придумать" in system


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


def content(number: bool = False) -> ContentPackage:
    text = "Согласование ускорилось на 37,5 %" if number else "Согласование стало быстрее"
    return ContentPackage(brief=brief(), facts=[Fact(fact_id="f001", text=text)])


def plan_slide() -> SlidePlan:
    return SlidePlan(
        slide_id="s02",
        intent=SlideIntent.EVIDENCE,
        headline="Согласование стало быстрее",
        fact_refs=["f001"],
    )


def zone_of(zone_id: str, role: TypeLevel, top: float) -> Zone:
    return Zone(
        zone_id=zone_id, role=role, capacity_chars=90, size_pt=12.0,
        x=EMU_PER_CM, y=int(top * EMU_PER_CM), cx=20 * EMU_PER_CM, cy=2 * EMU_PER_CM,
    )


def design_system(card: ExamplePassport) -> DesignSystem:
    grid = GridSpec(
        width_emu=12192000, height_emu=6858000, aspect="16:9",
        margins=Margins(left=685800, right=685800, top=457200, bottom=457200),
        columns=12, gutter_emu=152400, column_width_emu=736600,
        content_width_emu=10820400, content_height_emu=5943600,
        spacing=SpacingScale(base_emu=152400, base_source="gutter", steps_in_margin=4),
    )
    recipe = Recipe(
        recipe_id="ex003", example_index=3, kind=RecipeKind.METRICS,
        zones=[
            zone_of("z01", TypeLevel.SLIDE_TITLE, 1),
            zone_of("z02", TypeLevel.DISPLAY, 5),
            zone_of("z03", TypeLevel.CAPTION, 9),
        ],
        passport=card, layout_name="Контент",
    )
    return DesignSystem(
        template_id="sha256:" + "a" * 64, source_name="синтетический",
        grid=grid, theme=ThemeInfo(), recipes=[recipe],
    )


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


@pytest.mark.asyncio
async def test_the_slide_without_numbers_gets_no_number_place(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Нарушитель: слайд без цифр в материале — места-числа нет ни в запросе, ни на слайде."""
    card = tile_passport()
    llm = FakeLlm({"p01": "Согласование стало быстрее", "p03": "Без ручного труда"})
    composer = SlideComposer(llm)

    composed = await composer.compose(
        plan_slide(),
        content(number=False),
        manifest,
        variant_a,
        1341,
        design_system=design_system(card),
        assignment=RecipeAssignment(slide_id="s02", recipe_id="ex003", reason="вид metrics"),
    )

    assert "p02" not in llm.asked[0]["response_schema"]["properties"]
    assert [block.zone_id for block in composed.blocks] == ["z01", "z03"]
    assert any("нет ни одной цифры" in note for note in composer.notes)


@pytest.mark.asyncio
async def test_the_slide_with_numbers_keeps_its_number_place(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма: цифра в фактах есть — место-число заказано и заполнено."""
    card = tile_passport()
    llm = FakeLlm({"p01": "Согласование ускорилось", "p02": "37,5 %", "p03": "За год"})
    composer = SlideComposer(llm)

    composed = await composer.compose(
        plan_slide(),
        content(number=True),
        manifest,
        variant_a,
        1341,
        design_system=design_system(card),
        assignment=RecipeAssignment(slide_id="s02", recipe_id="ex003", reason="вид metrics"),
    )

    assert "p02" in llm.asked[0]["response_schema"]["properties"]
    assert [block.zone_id for block in composed.blocks] == ["z01", "z02", "z03"]
