"""Текст пишется под места примера. Change `the-text-is-written-for-the-places` (план Б, шаг 3).

Сценарии — из дельты `openspec/changes/the-text-is-written-for-the-places/specs/slide-composition/`.
Паспорт синтетический: проверяется правило, а не конкретный шаблон (C6). Там, где речь
о ширине букв, замер идёт настоящим вписыванием (`passport.fit_measure`) — тем же, которым
мерился паспорт: если проверять подделкой, обещание «место держит столько знаков» ничем
не подтверждено.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deckforge.composition.assign import RecipeAssignment
from deckforge.composition.composer import PLACES_PROMPT_VERSION, SlideComposer
from deckforge.composition.passport import fit_measure
from deckforge.composition.places import (
    blocks_for_places,
    by_place,
    merged,
    overflowing_places,
    places_brief,
    response_schema,
    shorten_request,
    trimmed_to_fit,
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


# --- паспорт и каталог ------------------------------------------------------------


def place(
    place_id: str,
    zone_id: str,
    role: TypeLevel = TypeLevel.BODY,
    chars: int = 90,
    kind: PlaceKind = PlaceKind.TEXT,
) -> Place:
    return Place(
        place_id=place_id, kind=kind, zone_id=zone_id, role=role, capacity_chars=chars
    )


def passport_with_row(cards: int = 5, places_in_card: int = 2) -> ExamplePassport:
    """Заголовок слайда одиночным местом и ряд из `cards` карточек по два места.

    Нумерация мест и зон сквозная (`p01`, `z01`, …), как её ставит паспорт: место
    принадлежит группе, а не номеру карточки.
    """
    groups = [
        PlaceGroup(
            group_id="g01",
            places=[place("p01", "z01", TypeLevel.SLIDE_TITLE, chars=60)],
        )
    ]
    number = 1
    for index in range(cards):
        card: list[Place] = []
        for position in range(places_in_card):
            number += 1
            card.append(
                place(
                    f"p{number:02d}",
                    f"z{number:02d}",
                    TypeLevel.CARD_TITLE if position == 0 else TypeLevel.BODY,
                    chars=24 if position == 0 else 90,
                )
            )
        groups.append(PlaceGroup(group_id=f"g{index + 2:02d}", places=card, row="r1"))
    return ExamplePassport(groups=groups)


def zones_of(card: ExamplePassport, **frame: int) -> list[Zone]:
    return [
        Zone(
            zone_id=item.zone_id or "",
            role=item.role or TypeLevel.BODY,
            capacity_chars=item.capacity_chars,
            **frame,
        )
        for item in card.places
        if item.kind is not PlaceKind.PICTURE
    ]


def recipe_of(card: ExamplePassport, *, recipe_id: str = "ex01", **frame: int) -> Recipe:
    return Recipe(
        recipe_id=recipe_id,
        example_index=1,
        kind=RecipeKind.CARDS,
        zones=zones_of(card, **frame),
        repeats=len(card.rows.get("r1") or []),
        passport=card,
        layout_name="Контент",
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


# --- схема ответа собирается из паспорта ------------------------------------------


def test_the_schema_names_every_place_with_its_own_limit() -> None:
    """Норма: одиночное место — поле с его пределом, ряд — массив ровно на назначенное."""
    card = passport_with_row(cards=5)
    schema = response_schema(card, {"r1": 3})

    assert schema["properties"]["p01"] == {"type": "string", "maxLength": 60, "minLength": 1}
    row = schema["properties"]["r1"]
    assert (row["minItems"], row["maxItems"]) == (3, 3)
    item = row["items"]
    assert item["required"] == ["t1", "t2"]
    assert item["properties"]["t1"]["maxLength"] == 24
    assert item["properties"]["t2"]["maxLength"] == 90
    assert item["additionalProperties"] is False
    assert schema["additionalProperties"] is False


def test_a_row_without_a_fill_is_not_in_the_schema() -> None:
    """Нарушитель: ряд, которому заполнение не назначено, у модели не просится."""
    card = passport_with_row(cards=2)
    second = PlaceGroup(
        group_id="g09", places=[place("p11", "z11", TypeLevel.CAPTION, chars=40)], row="r2"
    )
    both = ExamplePassport(groups=[*card.groups, second])

    schema = response_schema(both, {"r1": 2})

    assert "r1" in schema["properties"]
    assert "r2" not in schema["properties"]
    assert "r2" not in schema["required"]


def test_the_retry_asks_the_measured_limit_not_the_one_that_failed() -> None:
    """Норма: повторный запрос сужает предел места, а не повторяет прежний."""
    card = passport_with_row(cards=2)

    schema = response_schema(card, {"r1": 2}, {"p01": 41, "p02": 12})

    assert schema["properties"]["p01"]["maxLength"] == 41
    assert schema["properties"]["r1"]["items"]["properties"]["t1"]["maxLength"] == 12
    # Место, которое встало, просится как прежде: сокращать написанное дважды незачем.
    assert schema["properties"]["r1"]["items"]["properties"]["t2"]["maxLength"] == 90


def test_the_brief_shows_the_model_the_places_not_the_zones() -> None:
    """Норма: в промпт уходят места, их ступени и пределы — не зоны и не координаты."""
    brief = places_brief(passport_with_row(cards=4), {"r1": 2})

    assert [item["place_id"] for item in brief["single_places"]] == ["p01"]
    assert brief["single_places"][0]["role"] == TypeLevel.SLIDE_TITLE.value
    row = brief["place_rows"][0]
    assert (row["row"], row["count"]) == ("r1", 2)
    assert [item["key"] for item in row["cells"]] == ["t1", "t2"]
    assert "z01" not in json.dumps(brief, ensure_ascii=False)


# --- ответ ложится в места один к одному ------------------------------------------


def test_the_answer_lands_in_the_places_one_to_one() -> None:
    """Норма: семь мест — семь блоков со своими зонами, ничего не снято и не склеено."""
    card = passport_with_row(cards=5)
    answer = {
        "p01": "Выручка выросла",
        "r1": [
            {"t1": "Подписки", "t2": "Рост на 37,5 % за год"},
            {"t1": "Услуги", "t2": "Рост на 12 %"},
            {"t1": "Оборудование", "t2": "Без изменений"},
        ],
    }

    blocks = blocks_for_places(card, {"r1": 3}, answer)

    assert len(blocks) == 7
    assert [block.zone_id for block in blocks] == [
        "z01", "z02", "z03", "z04", "z05", "z06", "z07"
    ]
    assert blocks[0].role is TextRole.TITLE
    assert all(block.role is TextRole.BODY for block in blocks[1:])
    assert blocks[2].text == "Рост на 37,5 % за год"
    assert len({block.block_id for block in blocks}) == 7


def test_a_place_the_model_left_empty_does_not_become_a_block() -> None:
    """Нарушитель: пустое место блоком не становится — выдумывать за модель нечем."""
    card = passport_with_row(cards=2)
    answer = {"p01": "Вывод", "r1": [{"t1": "Подписки", "t2": "   "}, {"t1": "", "t2": "Рост"}]}

    blocks = blocks_for_places(card, {"r1": 2}, answer)

    assert [block.zone_id for block in blocks] == ["z01", "z02", "z05"]


def test_groups_beyond_the_fill_are_not_filled() -> None:
    """Нарушитель: ответ длиннее назначенного заполнения не даёт лишних блоков."""
    card = passport_with_row(cards=5)
    answer = {"p01": "Вывод", "r1": [{"t1": f"К{index}", "t2": "Текст"} for index in range(5)]}

    blocks = blocks_for_places(card, {"r1": 2}, answer)

    assert len(blocks) == 5  # заголовок и две карточки по два места


# --- ширина букв: замер, повтор, обрезка ------------------------------------------


def narrow_zone_recipe() -> tuple[Recipe, ExamplePassport]:
    """Пример с настоящей рамкой: место заголовка держит короткую строку, тело — просторное."""
    card = ExamplePassport(
        groups=[
            PlaceGroup(
                group_id="g01",
                places=[
                    place("p01", "z01", TypeLevel.SLIDE_TITLE, chars=90),
                    place("p02", "z02", TypeLevel.BODY, chars=90),
                ],
            )
        ]
    )
    zones = [
        Zone(
            zone_id="z01",
            role=TypeLevel.SLIDE_TITLE,
            capacity_chars=90,
            size_pt=28,
            x=EMU_PER_CM,
            y=EMU_PER_CM,
            cx=14 * EMU_PER_CM,
            cy=2 * EMU_PER_CM,
        ),
        Zone(
            zone_id="z02",
            role=TypeLevel.BODY,
            capacity_chars=90,
            size_pt=14,
            x=EMU_PER_CM,
            y=8 * EMU_PER_CM,
            cx=20 * EMU_PER_CM,
            cy=6 * EMU_PER_CM,
        ),
    ]
    return (
        Recipe(
            recipe_id="ex01",
            example_index=1,
            kind=RecipeKind.TEXT,
            zones=zones,
            passport=card,
            layout_name="Контент",
        ),
        card,
    )


def test_a_place_that_does_not_fit_by_glyph_width_is_named(
    manifest: TemplateManifest,
) -> None:
    """Нарушитель: текст в пределе знаков, но шрифтом не встаёт — место названо."""
    recipe, card = narrow_zone_recipe()
    fits = fit_measure(manifest, design_system(recipe), None)
    long = "Вся выручка направления выросла на тридцать семь процентов"
    blocks = [
        TextBlock(block_id="b01", role=TextRole.TITLE, text=long, zone_id="z01"),
        TextBlock(block_id="b02", role=TextRole.BODY, text="Коротко", zone_id="z02"),
    ]

    limits = overflowing_places(recipe, fits, blocks)

    assert "z01" in limits, "узкая рамка заголовка обязана отвергнуть длинную строку"
    assert "z02" not in limits
    assert 0 < limits["z01"] < len(long)
    assert by_place(card, limits) == {"p01": limits["z01"]}


def test_text_that_fits_asks_for_no_retry(manifest: TemplateManifest) -> None:
    """Норма: всё встало — повторный запрос не нужен."""
    recipe, _card = narrow_zone_recipe()
    fits = fit_measure(manifest, design_system(recipe), None)
    blocks = [
        TextBlock(block_id="b01", role=TextRole.TITLE, text="Рост", zone_id="z01"),
        TextBlock(block_id="b02", role=TextRole.BODY, text="Подписки выросли", zone_id="z02"),
    ]

    assert overflowing_places(recipe, fits, blocks) == {}


def test_the_shorten_request_names_the_places_and_their_limits() -> None:
    """Норма: повторный запрос называет места и пределы, а не «сократи текст»."""
    text = shorten_request({"p02": 12, "p01": 41})

    assert text.index("p01") < text.index("p02"), "порядок мест воспроизводим"
    assert "p01 — до 41 знаков" in text
    assert "p02 — до 12 знаков" in text


def test_trimming_by_words_is_the_last_step_and_is_named() -> None:
    """Норма: обрезка идёт по словам и возвращает, что было и что осталось."""
    blocks = [
        TextBlock(
            block_id="b01",
            role=TextRole.TITLE,
            text="Выручка направления выросла на тридцать семь процентов",
            zone_id="z01",
        ),
        TextBlock(block_id="b02", role=TextRole.BODY, text="Коротко", zone_id="z02"),
    ]

    trimmed, cut = trimmed_to_fit(blocks, {"z01": 20})

    assert trimmed[0].text == "Выручка направления"
    assert not trimmed[0].text.endswith(" ")
    assert cut == {"b01": (54, 19)}
    assert trimmed[1].text == "Коротко", "встал — не режем"


def test_the_retry_does_not_take_away_what_was_written() -> None:
    """Норма: пустое место в ответе повтора оставляет прежний текст, а не отнимает его.

    Повтор просит сократить одно место, а схема требует все: модель переписывает заодно
    и остальные. Пустая строка при этом — осечка, а не решение «здесь ничего не надо»
    (WorkSpace `ex024`, место заголовка в девять знаков: слайд остался без заголовка).
    """
    first = {"p01": "Выручка выросла", "r1": [{"t1": "Подписки", "t2": "Плюс 37,5 %"}]}
    retried = {"p01": "", "r1": [{"t1": "Подписки", "t2": ""}]}

    assert merged(first, retried) == first


def test_the_retry_replaces_only_what_it_wrote() -> None:
    """Норма: непустое место повтора заменяет прежнее, лишние группы ответа не теряются."""
    first = {"p01": "Длинный заголовок", "r1": [{"t1": "Подписки"}, {"t1": "Услуги"}]}
    retried = {"p01": "Рост", "r1": [{"t1": "Подписки и услуги"}]}

    assert merged(first, retried) == {
        "p01": "Рост",
        "r1": [{"t1": "Подписки и услуги"}, {"t1": "Услуги"}],
    }


def test_a_place_that_holds_no_word_is_never_asked_for_zero_chars() -> None:
    """Нарушитель: предел схемы не бывает нулевым — иначе грамматика отдаёт пустое место."""
    card = passport_with_row(cards=2)

    schema = response_schema(card, {"r1": 2}, {"p01": 0})

    assert schema["properties"]["p01"]["maxLength"] == 1
    assert schema["properties"]["p01"]["minLength"] == 1


# --- промпт 2.0.0 ----------------------------------------------------------------


def test_the_places_prompt_speaks_of_places_and_not_of_placeholders() -> None:
    """Норма: версия промпта существует, рендерится и не просит координат."""
    bundle = get_prompt_registry().load("slide_composer", version=PLACES_PROMPT_VERSION)
    card = passport_with_row(cards=3)
    system, user = bundle.render(
        slide=plan_slide(),
        facts=[Fact(fact_id="f001", text="Выручка выросла на 37,5 %")],
        recipe_kind=RecipeKind.CARDS.value,
        variant="A",
        seed=1341,
        language="ru",
        brief=brief(),
        no_think=False,
        **places_brief(card, {"r1": 2}),
    )

    assert "p01" in user and "t1" in user
    assert "заполнить ровно 2" in user
    assert "до 24 знаков" in user
    assert "координат" in system
    assert bundle.response_schema is None, "схема ответа собирается из паспорта, не из файла"


# --- слайд целиком: композитор идёт путём by_example ------------------------------


class FakeLlm:
    """Модель, отвечающая заранее заготовленными ответами по порядку запросов."""

    model = "fake"

    def __init__(self, *payloads: dict[str, Any]) -> None:
        self.payloads = list(payloads)
        self.asked: list[dict[str, Any]] = []

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        self.asked.append({"messages": messages, **kwargs})
        payload = self.payloads[min(len(self.asked) - 1, len(self.payloads) - 1)]
        return Completion(text=json.dumps(payload, ensure_ascii=False), model=self.model)


def brief() -> Brief:
    return Brief(purpose="product", audience="правление", target_slides=6, language="ru")


def content() -> ContentPackage:
    return ContentPackage(
        brief=brief(),
        facts=[
            Fact(fact_id="f001", text="Выручка подписок выросла на 37,5 %"),
            Fact(fact_id="f002", text="Услуги прибавили 12 %"),
        ],
    )


def plan_slide() -> SlidePlan:
    return SlidePlan(
        slide_id="s03",
        intent=SlideIntent.EVIDENCE,
        headline="Выручка выросла",
        fact_refs=["f001", "f002"],
        suggested_visual="cards",
    )


@pytest.fixture
def variant_a() -> VariantProfile:
    return load_variant_profiles()["A"]


@pytest.mark.asyncio
async def test_the_slide_is_composed_from_the_places_of_the_assigned_example(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма: слайд собран по местам назначенного примера, причина — из назначения."""
    card = passport_with_row(cards=3)
    recipe = recipe_of(card)
    llm = FakeLlm(
        {
            "p01": "Выручка выросла",
            "r1": [
                {"t1": "Подписки", "t2": "Плюс 37,5 % за год"},
                {"t1": "Услуги", "t2": "Плюс 12 %"},
            ],
        }
    )
    composer = SlideComposer(llm)

    composed = await composer.compose(
        plan_slide(),
        content(),
        manifest,
        variant_a,
        1341,
        design_system=design_system(recipe),
        assignment=RecipeAssignment(
            slide_id="s03", recipe_id="ex01", reason="вид cards заказан планом", row_fill={"r1": 2}
        ),
    )

    assert composed.recipe_id == "ex01"
    assert composed.by_recipe, "каждый блок стоит в зоне примера"
    assert [block.zone_id for block in composed.blocks] == ["z01", "z02", "z03", "z04", "z05"]
    assert composed.provenance.prompt_version == f"slide_composer@{PLACES_PROMPT_VERSION}"
    assert composer.choices["s03"]["why"] == "вид cards заказан планом"
    assert composer.choices["s03"]["recipe_id"] == "ex01"
    # Схема ответа ушла в запрос: предел держит грамматика, а не просьба в промпте.
    assert llm.asked[0]["response_schema"]["properties"]["r1"]["maxItems"] == 2


@pytest.mark.asyncio
async def test_a_slide_without_an_assignment_goes_the_old_way(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Нарушитель: назначения нет — путь прежний, схема ответа доменная (`SlideIR`)."""
    llm = FakeLlm(
        {
            "blocks": [
                {"type": "text", "block_id": "b01", "role": "title", "text": "Выручка выросла"},
                {
                    "type": "bullets",
                    "block_id": "b02",
                    "placeholder_idx": 1,
                    "items": [{"text": "Подписки плюс 37,5 %"}, {"text": "Услуги плюс 12 %"}],
                },
            ]
        }
    )
    composer = SlideComposer(llm)

    composed = await composer.compose(plan_slide(), content(), manifest, variant_a, 1341)

    assert composed.recipe_id is None
    assert not composed.by_recipe
    assert any(block.type == "bullets" for block in composed.blocks)


@pytest.mark.asyncio
async def test_an_assignment_without_an_example_goes_the_old_way(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Нарушитель: назначение без примера (`recipe_id is None`) путём мест не идёт.

    Рецепт слайду при этом достаётся — его берёт прежний путь своим отбором
    (`pick_recipe`): назначение без примера не запрещает старый выбор, а обходит новый.
    """
    llm = FakeLlm(
        {
            "blocks": [
                {"type": "text", "block_id": "b01", "role": "title", "text": "Выручка выросла"}
            ]
        }
    )
    composer = SlideComposer(llm)

    composed = await composer.compose(
        plan_slide(),
        content(),
        manifest,
        variant_a,
        1341,
        design_system=design_system(recipe_of(passport_with_row(cards=2))),
        assignment=RecipeAssignment(
            slide_id="s03", recipe_id=None, reason="примера вида smartart у шаблона нет"
        ),
    )

    assert composed.provenance.prompt_version.endswith("@1.5.0"), "промпт прежнего пути"


@pytest.mark.asyncio
async def test_one_retry_shortens_the_place_that_did_not_fit(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Нарушитель: не встало по ширине — один повторный запрос с замеренным пределом."""
    recipe, card = narrow_zone_recipe()
    long = "Вся выручка направления выросла на тридцать семь с половиной процентов"
    llm = FakeLlm(
        {"p01": long, "p02": "Подписки и услуги"},
        {"p01": "Выручка выросла", "p02": "Подписки и услуги"},
    )
    composer = SlideComposer(llm)

    composed = await composer.compose(
        plan_slide(),
        content(),
        manifest,
        variant_a,
        1341,
        design_system=design_system(recipe),
        assignment=RecipeAssignment(
            slide_id="s03", recipe_id="ex01", reason="вид text заказан планом"
        ),
    )

    assert len(llm.asked) == 2, "повтор один, а не цикл"
    second = llm.asked[1]
    assert "p01 — до" in second["messages"][-1]["content"]
    assert second["response_schema"]["properties"]["p01"]["maxLength"] < len(long)
    title = composed.block("b01")
    assert title is not None and isinstance(title, TextBlock)
    assert title.text == "Выручка выросла"
    assert any("не встали места p01" in note for note in composer.notes)
    assert card.place("p01") is not None


@pytest.mark.asyncio
async def test_after_the_retry_the_text_is_trimmed_by_words_and_named(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Норма: повтор не помог — обрезка по словам последним шагом и с заметкой."""
    recipe, _card = narrow_zone_recipe()
    long = "Вся выручка направления выросла на тридцать семь с половиной процентов"
    llm = FakeLlm({"p01": long, "p02": "Подписки и услуги"})  # модель отвечает тем же дважды
    composer = SlideComposer(llm)

    composed = await composer.compose(
        plan_slide(),
        content(),
        manifest,
        variant_a,
        1341,
        design_system=design_system(recipe),
        assignment=RecipeAssignment(
            slide_id="s03", recipe_id="ex01", reason="вид text заказан планом"
        ),
    )

    title = composed.block("b01")
    assert title is not None
    assert len(title.text) < len(long)
    assert long.startswith(title.text), "обрезка по словам с начала, а не пересказ"
    assert any("обрезан по словам под место" in note for note in composer.notes)


@pytest.mark.asyncio
async def test_a_place_too_small_for_one_word_keeps_its_text(
    manifest: TemplateManifest, variant_a: VariantProfile
) -> None:
    """Нарушитель: место не держит и слова — повтора нет, текст остался, случай назван.

    Тот самый случай WorkSpace `ex024`: место заголовка в девять знаков, ёмкость которого
    паспорт посчитал пробными узкими буквами. Повторный запрос «до нуля знаков» вернул бы
    пустую строку, и слайд остался бы без заголовка.
    """
    card = ExamplePassport(
        groups=[
            PlaceGroup(
                group_id="g01",
                places=[place("p01", "z01", TypeLevel.SLIDE_TITLE, chars=9)],
            )
        ]
    )
    recipe = Recipe(
        recipe_id="ex024",
        example_index=1,
        kind=RecipeKind.TEXT,
        zones=[
            Zone(
                zone_id="z01",
                role=TypeLevel.SLIDE_TITLE,
                capacity_chars=9,
                size_pt=40,
                x=EMU_PER_CM,
                y=EMU_PER_CM,
                cx=EMU_PER_CM,
                cy=EMU_PER_CM,
            )
        ],
        passport=card,
        layout_name="Контент",
    )
    llm = FakeLlm({"p01": "Автоматиз"})
    composer = SlideComposer(llm)

    composed = await composer.compose(
        plan_slide(),
        content(),
        manifest,
        variant_a,
        1341,
        design_system=design_system(recipe),
        assignment=RecipeAssignment(slide_id="s03", recipe_id="ex024", reason="вид text"),
    )

    assert len(llm.asked) == 1, "сокращать до нуля знаков нечего — повтора нет"
    title = composed.block("b01")
    assert title is not None and isinstance(title, TextBlock)
    assert title.text == "Автоматиз", "место без текста — это потеря, а не сокращение"
    assert any("не держат и одного слова" in note for note in composer.notes)
