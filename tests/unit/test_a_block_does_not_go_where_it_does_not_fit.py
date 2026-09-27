"""Блок не встаёт в зону, которая его не держит. RG43 и RG44
(`docs/agents/tasks-26-09.md`), change `a-block-does-not-go-where-it-does-not-fit`.

Первый замер холодным разбором дал восемь ошибок аудита на трёх колодах. Семь из них —
две причины, и обе здесь.

**RG43.** У VK Education рецепт `ex044` несёт четыре зоны `card_title` вместимостью
**два знака** и четыре `caption` вместимостью **сорок четыре**. Три факта слайда ушли
в двухзнаковые: `_zone_for` выбирал зону по ступени роли (`body → card_title`)
и вместимость не спрашивал вовсе. Вписывание сообщило, что текст не помещается и в два
слова, сняло его — слайды s03 и s07 остались с одним заголовком (по две ошибки на каждом).

**RG44.** У VK WorkSpace план ставил на титульный слайд два факта, а у обложки шаблона
одна текстовая зона. Факты снимались, аудит считал это потерей содержания и был прав:
неправ был план. Правило 9а промпта `deck_planner@1.3.1` это закрывает.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from deckforge.composition.recipe_binding import bind_to_recipe
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import BulletItem, BulletsBlock, SlideIR, TextBlock
from deckforge.registry import get_prompt_registry

#: Настоящие числа рецепта `ex044` VK Education: столько держат его зоны.
CARD_CHARS, CAPTION_CHARS = 2, 44

FACT = "AI генерирует презентацию по контенту за минуты"


def zone(zone_id: str, role: TypeLevel, *, chars: int, repeat: int | None = None) -> Zone:
    return Zone(
        zone_id=zone_id, xml_id=int(zone_id[1:]), role=role, repeat=repeat,
        capacity_chars=chars, size_pt=16,
    )


def metrics_recipe() -> Recipe:
    """Рецепт по образцу `ex044`: заголовок, четыре названия карточек, четыре подписи."""
    zones = [zone("z987", TypeLevel.SLIDE_TITLE, chars=60)]
    for index in range(4):
        zones.append(zone(f"z{988 + index}", TypeLevel.CARD_TITLE, chars=CARD_CHARS))
        zones.append(zone(f"z{992 + index}", TypeLevel.CAPTION, chars=CAPTION_CHARS))
    return Recipe(
        recipe_id="ex044", example_index=44, kind=RecipeKind.METRICS, repeats=0, zones=zones
    )


def slide_ir(*blocks: object) -> SlideIR:
    return SlideIR(
        slide_id="s03", layout_id="L07", variant="A", blocks=list(blocks)  # type: ignore[arg-type]
    )


def body(count: int) -> list[object]:
    return [
        TextBlock(block_id=f"b{index}", role=TextRole.BODY, text=f"{FACT} {index}")
        for index in range(count)
    ]


# --- RG43: вместимость раньше ступени --------------------------------------------


def test_a_fact_goes_to_the_zone_that_holds_it() -> None:
    """Нарушитель: зона своей ступени держит два знака, чужая — сорок четыре.

    До правки все три факта уходили в двухзнаковые `card_title`, и слайд пустел.
    """
    notes: list[str] = []

    bound = bind_to_recipe(slide_ir(*body(3)), metrics_recipe(), notes)

    placed = {block.zone_id for block in bound.blocks}
    assert placed <= {"z992", "z993", "z994", "z995"}, f"факты ушли не в подписи: {placed}"
    assert len(bound.blocks) == 3
    assert all(len(block.text) > CARD_CHARS for block in bound.blocks)  # type: ignore[union-attr]


def test_the_level_still_wins_among_zones_that_hold_the_text() -> None:
    """Норма: обе зоны держат текст — ступень решает, как решала раньше."""
    notes: list[str] = []
    recipe = Recipe(
        recipe_id="ex001", example_index=1, kind=RecipeKind.TEXT,
        zones=[
            zone("z1", TypeLevel.SLIDE_TITLE, chars=60),
            zone("z2", TypeLevel.CAPTION, chars=200),
            zone("z3", TypeLevel.BODY, chars=200),
        ],
    )

    bound = bind_to_recipe(slide_ir(*body(1)), recipe, notes)

    assert [block.zone_id for block in bound.blocks] == ["z3"], "ступень уступила без нужды"


def test_a_bullet_goes_to_the_card_text_not_its_label() -> None:
    """Нарушитель в повторах: пункт списка вставал в название карточки на два знака."""
    notes: list[str] = []
    zones = [zone("z987", TypeLevel.SLIDE_TITLE, chars=60)]
    for index in range(2):
        zones.append(zone(f"z{988 + index}", TypeLevel.CARD_TITLE, chars=CARD_CHARS, repeat=index))
        zones.append(zone(f"z{992 + index}", TypeLevel.CAPTION, chars=CAPTION_CHARS, repeat=index))
    row = Recipe(
        recipe_id="ex044", example_index=44, kind=RecipeKind.CARDS, repeats=2, zones=zones
    )
    bullets = BulletsBlock(
        block_id="b", items=[BulletItem(text=f"{FACT} {n}") for n in range(2)]
    )

    bound = bind_to_recipe(slide_ir(bullets), row, notes)

    assert {block.zone_id for block in bound.blocks} == {"z992", "z993"}


def test_a_zone_without_a_measured_capacity_is_still_a_candidate() -> None:
    """Норма: вместимость ноль — её не посчитали, и отсеивать зону по незнанию нельзя."""
    notes: list[str] = []
    recipe = Recipe(
        recipe_id="ex002", example_index=2, kind=RecipeKind.TEXT,
        zones=[
            zone("z1", TypeLevel.SLIDE_TITLE, chars=60),
            Zone(zone_id="z2", xml_id=2, role=TypeLevel.BODY, capacity_chars=0),
        ],
    )

    bound = bind_to_recipe(slide_ir(*body(1)), recipe, notes)

    assert [block.zone_id for block in bound.blocks] == ["z2"]


# --- RG44: структурный слайд без фактов -------------------------------------------


def test_the_planner_forbids_facts_on_a_structural_slide() -> None:
    """Промпт планировщика прямо запрещает факты на обложке, разделителе и финале.

    Проверяется активная версия, а не номер: номер сменится, правило обязано остаться.
    """
    bundle = get_prompt_registry().load("deck_planner")
    system = Path(bundle.ref.path if hasattr(bundle.ref, "path") else "").name

    registry = yaml.safe_load(Path("prompts/registry.yaml").read_text(encoding="utf-8"))
    active = registry["skills"]["deck_planner"]["active"]
    text = (Path("prompts/deck_planner") / active / "system.j2").read_text(encoding="utf-8")

    assert "фактов НЕ несут" in text, f"правила 9а нет в активной версии ({system})"
    assert "`fact_refs`" in text


def test_the_previous_version_did_not_have_the_rule() -> None:
    """Нарушитель: в 1.3.0 правила не было — иначе тест не проверял бы ничего."""
    old = (Path("prompts/deck_planner/1.3.0/system.j2")).read_text(encoding="utf-8")

    assert "фактов НЕ несут" not in old
