"""Рецепт обязан вмещать текст слайда. Change `a-recipe-must-fit-the-text`, RG23 и RG24
(`docs/agents/tasks-24-09.md`).

Четыре прогона 24.09 показали две стороны одной дыры: на холодном шаблоне единственный
рецепт имел зоны по два знака, и по слайду разъехались одиночные буквы; на VK Tech откат
структурного слайда дал обложке ряд карточек, набить которые нечем.

Сценарии — из дельты `openspec/changes/a-recipe-must-fit-the-text/specs/slide-composition/`.
Каталог синтетический: проверяется правило отбора, а не конкретный шаблон. Замер на
шаблоне кейса идёт отдельным тестом и без файла пропускается.
"""

from __future__ import annotations

from deckforge.composition.recipe_binding import bind_to_recipe
from deckforge.composition.recipe_picker import pick_recipe
from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import SlideIntent, TextRole
from deckforge.domain.plan import SlidePlan
from deckforge.domain.slide import BulletItem, BulletsBlock, SlideIR, TextBlock
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template

HEADLINE = "Правки занимают минуты, а не дни"


def zone(zone_id: str, role: TypeLevel, *, repeat: int | None = None, chars: int = 80) -> Zone:
    return Zone(
        zone_id=zone_id, xml_id=int(zone_id[1:]), role=role, repeat=repeat, capacity_chars=chars
    )


def recipe(
    index: int, kind: RecipeKind, *, repeats: int = 0, zones: list[Zone] | None = None
) -> Recipe:
    return Recipe(
        recipe_id=f"ex{index:03d}",
        example_index=index,
        kind=kind,
        repeats=repeats,
        zones=zones or [zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY)],
    )


def plan(**kwargs: object) -> SlidePlan:
    data: dict[str, object] = {
        "slide_id": "s01",
        "intent": SlideIntent.EVIDENCE,
        "headline": HEADLINE,
        "fact_refs": ["f1"],
    }
    data.update(kwargs)
    return SlidePlan(**data)  # type: ignore[arg-type]


# --- вместимость (RG23) ---------------------------------------------------------


def test_a_recipe_whose_zones_hold_two_characters_is_not_picked() -> None:
    """Нарушитель находки 2: холодный шаблон, зоны по два знака.

    Такой рецепт считался вмещающим целый слайд, `_clip` резал каждую строку до двух
    знаков, и по слайду разъезжались одиночные буквы.
    """
    tiny = recipe(
        6,
        RecipeKind.TEXT,
        zones=[
            zone("z1", TypeLevel.SLIDE_TITLE, chars=2),
            zone("z2", TypeLevel.BODY, chars=2),
        ],
    )

    assert pick_recipe(plan(suggested_visual="text"), [tiny], needs_chars=200) is None


def test_a_recipe_that_holds_the_headline_and_the_facts_is_picked() -> None:
    """Норма: зоны вмещают то, что слайду есть сказать."""
    roomy = recipe(1, RecipeKind.TEXT)

    assert pick_recipe(plan(suggested_visual="text"), [roomy], needs_chars=120) is roomy


def test_a_catalogue_of_recipes_that_do_not_hold_gives_nothing() -> None:
    """Каталог непуст, но вмещающего нет — слайд собирается по макету."""
    tiny = [
        recipe(n, RecipeKind.TEXT, zones=[zone("z1", TypeLevel.SLIDE_TITLE, chars=3)])
        for n in (1, 2, 3)
    ]

    assert pick_recipe(plan(suggested_visual="text"), tiny, needs_chars=200) is None


def test_a_zone_without_a_counted_capacity_does_not_block_the_recipe() -> None:
    """Вместимость ноль — её не удалось посчитать, и условие молчит.

    Отсеять рецепт из-за собственного незнания хуже, чем пропустить: у фигуры примера
    может не быть кегля, и тогда вместимость зоны неизвестна, а не мала.
    """
    unknown = recipe(
        1,
        RecipeKind.TEXT,
        zones=[zone("z1", TypeLevel.SLIDE_TITLE, chars=0), zone("z2", TypeLevel.BODY, chars=0)],
    )

    assert pick_recipe(plan(suggested_visual="text"), [unknown], needs_chars=200) is unknown


# --- откат структурного слайда (RG24) -------------------------------------------


def test_a_title_slide_does_not_fall_back_to_a_recipe_with_repeats() -> None:
    """Нарушитель находки 3: обложке достался ряд карточек.

    Содержание структурного слайда — заголовок, а не список: повторы остаются пустыми,
    вёрстка их удаляет, и на слайде остаются обрезанный заголовок и логотип.
    """
    notes: list[str] = []
    cards = recipe(
        24,
        RecipeKind.CARDS,
        repeats=3,
        zones=[
            zone("z1", TypeLevel.SLIDE_TITLE),
            zone("z10", TypeLevel.BODY, repeat=0),
            zone("z11", TypeLevel.BODY, repeat=1),
            zone("z12", TypeLevel.BODY, repeat=2),
        ],
    )

    picked = pick_recipe(plan(intent=SlideIntent.TITLE), [cards], needs_chars=60, notes=notes)

    assert picked is None
    assert any("по макету" in note for note in notes), "отказ отката не назван"


def test_a_title_slide_falls_back_to_a_recipe_without_repeats() -> None:
    """Норма: содержательный рецепт без повторов обложке годится, и откат назван."""
    notes: list[str] = []
    plain = recipe(1, RecipeKind.TEXT)

    picked = pick_recipe(plan(intent=SlideIntent.TITLE), [plain], needs_chars=60, notes=notes)

    assert picked is plain
    assert any("cover" in note for note in notes), "откат не назван"


def test_a_structural_slide_still_prefers_its_own_kind() -> None:
    """Норма к обоим правилам: свой вид есть — ни вместимость, ни повторы его не трогают."""
    own = recipe(2, RecipeKind.COVER)
    notes: list[str] = []

    picked = pick_recipe(plan(intent=SlideIntent.TITLE), [own], needs_chars=60, notes=notes)

    assert picked is own
    assert notes == []


# --- обрезка называется ----------------------------------------------------------


def slide_ir(blocks: list[object]) -> SlideIR:
    return SlideIR(
        slide_id="s01",
        layout_id="L07",
        variant="A",
        blocks=blocks,  # type: ignore[arg-type]
    )


def test_a_text_cut_in_half_is_named_in_the_notes() -> None:
    """Нарушитель: от текста осталось меньше половины.

    Отбор делает такие случаи редкими, но не невозможными: модель пишет длиннее,
    чем обещала. Молчаливая обрезка — подмена содержания, о которой никто не узнает.
    """
    notes: list[str] = []
    narrow = recipe(1, RecipeKind.TEXT, zones=[zone("z1", TypeLevel.SLIDE_TITLE, chars=6)])
    composed = slide_ir([TextBlock(block_id="t", role=TextRole.TITLE, text=HEADLINE)])

    bind_to_recipe(composed, narrow, notes)

    assert any("обрезан" in note and "s01" in note for note in notes)


def test_a_text_that_fits_is_not_named() -> None:
    """Норма: текст влез — оговорки нет."""
    notes: list[str] = []
    roomy = recipe(1, RecipeKind.TEXT)
    composed = slide_ir(
        [
            TextBlock(block_id="t", role=TextRole.TITLE, text=HEADLINE),
            BulletsBlock(block_id="b", role=TextRole.BODY, items=[BulletItem(text="Раз")]),
        ]
    )

    bind_to_recipe(composed, roomy, notes)

    assert notes == []


# --- замер на шаблоне кейса -------------------------------------------------------


def test_the_cover_of_a_real_template_is_never_an_empty_row_of_cards() -> None:
    """Замер RG24: VK Tech, слайд `s01` — обложка с текстом либо макет, но не пустой ряд.

    У этого шаблона нет ни `cover`, ни `section`, ни `final`, поэтому сюда приходит
    именно откат.
    """
    manifest = TemplateParser().parse(case_template("VK Tech шаблон.pptx"), use_cache=False)
    recipes = derive(manifest).recipes

    picked = pick_recipe(plan(intent=SlideIntent.TITLE), recipes, needs_chars=len(HEADLINE))

    assert picked is None or not picked.repeats, "обложке достался ряд повторов"
