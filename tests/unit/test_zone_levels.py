"""Блок кладётся в зону своей ступени. Change `a-block-goes-to-a-zone-of-its-level`,
таск RG30 (`docs/agents/tasks-25-09.md`).

Превью колод 24.09: вверху мелкая строка — заголовок слайда, под ней огромный текст —
тело. `_free_zones` раздавал зоны по порядку блоков от крупной ступени к мелкой, и первый
же блок тела забирал зону разделителя: на `ex018` VK WorkSpace (им собраны четыре слайда
из десяти) — `display` на 54 pt при свободной `body` на 18 pt.

Сценарии — из дельты `openspec/changes/a-block-goes-to-a-zone-of-its-level/specs/`.
"""

from __future__ import annotations

import pytest

from deckforge.composition.recipe_binding import ROLE_LEVELS, bind_to_recipe
from deckforge.designsystem import derive
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template


def zone(zone_id: str, role: TypeLevel, *, area: int = 100, repeat: int | None = None) -> Zone:
    """Зона с рамкой `area × 100` EMU: по площади рамки выбирается зона внутри ступени."""
    return Zone(
        zone_id=zone_id,
        xml_id=int(zone_id[1:]),
        role=role,
        repeat=repeat,
        capacity_chars=200,
        x=0,
        y=0,
        cx=area,
        cy=100,
    )


def recipe(*zones: Zone, kind: RecipeKind = RecipeKind.TEXT) -> Recipe:
    return Recipe(recipe_id="ex018", example_index=18, kind=kind, zones=list(zones))


def slide(*blocks: TextBlock) -> SlideIR:
    return SlideIR(slide_id="s05", layout_id="L01", variant="A", blocks=list(blocks))


TITLE = TextBlock(block_id="t", role=TextRole.TITLE, text="Автоматическая генерация")
BODY = TextBlock(block_id="b", role=TextRole.BODY, text="Анализ шаблона, извлечение структуры")


def placement(ir: SlideIR) -> dict[str, str | None]:
    return {block.block_id: block.zone_id for block in ir.blocks}


# --- сценарии дельты ------------------------------------------------------------------


def test_the_body_goes_to_its_own_level_not_to_the_largest_free_one() -> None:
    """Нарушитель до правки: тело уходило в `display`, как на `ex018`."""
    notes: list[str] = []
    ir = bind_to_recipe(
        slide(TITLE, BODY),
        recipe(
            zone("z718", TypeLevel.SLIDE_TITLE),
            zone("z719", TypeLevel.BODY),
            zone("z720", TypeLevel.DISPLAY),
        ),
        notes,
    )

    assert placement(ir) == {"t": "z718", "b": "z719"}
    assert notes == []


def test_without_a_body_zone_the_body_takes_body_large_without_a_note() -> None:
    notes: list[str] = []
    ir = bind_to_recipe(
        slide(TITLE, BODY),
        recipe(
            zone("z1", TypeLevel.SLIDE_TITLE),
            zone("z2", TypeLevel.BODY_LARGE),
            zone("z3", TypeLevel.DISPLAY),
        ),
        notes,
    )

    assert placement(ir)["b"] == "z2"
    assert notes == []


def test_only_a_display_zone_left_takes_the_body_and_says_so() -> None:
    notes: list[str] = []
    ir = bind_to_recipe(
        slide(TITLE, BODY),
        recipe(zone("z1", TypeLevel.SLIDE_TITLE), zone("z3", TypeLevel.DISPLAY)),
        notes,
    )

    assert placement(ir)["b"] == "z3"
    assert len(notes) == 1
    assert "зоны своей ступени" in notes[0] and "ex018" in notes[0] and "display" in notes[0]


def test_a_cover_puts_the_title_into_display_without_a_note() -> None:
    notes: list[str] = []
    ir = bind_to_recipe(
        slide(TITLE),
        recipe(
            zone("z1", TypeLevel.SLIDE_TITLE),
            zone("z2", TypeLevel.DISPLAY),
            kind=RecipeKind.COVER,
        ),
        notes,
    )

    title = ir.blocks[0]
    assert title.zone_id == "z2"
    assert title.role is TextRole.TITLE, "заголовок в зоне display обязан остаться заголовком"
    assert notes == []


def test_two_body_blocks_go_to_body_zones_from_the_largest() -> None:
    second = TextBlock(block_id="b2", role=TextRole.BODY, text="Второй абзац")
    ir = bind_to_recipe(
        slide(TITLE, BODY, second),
        recipe(
            zone("z1", TypeLevel.SLIDE_TITLE),
            # Номер зоны нарочно против площади: раньше внутри ступени решал номер.
            zone("z4", TypeLevel.BODY, area=300),
            zone("z5", TypeLevel.BODY, area=900),
        ),
    )

    assert placement(ir) == {"t": "z1", "b": "z5", "b2": "z4"}


# --- норма и границы ------------------------------------------------------------------


def test_levels_that_match_one_to_one_are_laid_out_as_before() -> None:
    """Норма: заголовок, подзаголовок, тело и подпись — каждый в своей ступени."""
    subtitle = TextBlock(block_id="s", role=TextRole.SUBTITLE, text="Подзаголовок")
    caption = TextBlock(block_id="c", role=TextRole.CAPTION, text="Источник: отчёт")
    notes: list[str] = []
    ir = bind_to_recipe(
        slide(TITLE, subtitle, BODY, caption),
        recipe(
            zone("z1", TypeLevel.SLIDE_TITLE),
            zone("z2", TypeLevel.SECTION_SUBTITLE),
            zone("z3", TypeLevel.BODY),
            zone("z4", TypeLevel.CAPTION),
        ),
        notes,
    )

    assert placement(ir) == {"t": "z1", "s": "z2", "b": "z3", "c": "z4"}
    assert notes == []


def test_a_foreign_level_below_is_taken_before_one_above() -> None:
    """Своей ступени нет: ближняя ниже лучше такой же ближней выше — лестница цела."""
    notes: list[str] = []
    ir = bind_to_recipe(
        slide(TITLE, BODY),
        recipe(
            zone("z1", TypeLevel.SLIDE_TITLE),
            zone("z2", TypeLevel.SECTION_SUBTITLE),
            zone("z3", TypeLevel.CAPTION),
        ),
        notes,
    )

    assert placement(ir)["b"] == "z3"
    assert notes and "caption" in notes[0]


def test_every_text_role_has_levels() -> None:
    assert set(ROLE_LEVELS) == set(TextRole)


def test_a_block_placed_by_its_level_keeps_its_role() -> None:
    ir = bind_to_recipe(
        slide(TITLE, BODY),
        recipe(zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY)),
    )
    assert [block.role for block in ir.blocks] == [TextRole.TITLE, TextRole.BODY]


# --- шаблон кейса ---------------------------------------------------------------------


def test_the_body_of_ex018_goes_to_the_body_zone_not_to_the_divider() -> None:
    """Тот самый рецепт VK WorkSpace из прогона 24.09: четыре слайда из десяти."""
    manifest = TemplateParser().parse(
        case_template("VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx"), use_cache=False
    )
    ex018 = next((r for r in derive(manifest).recipes if r.recipe_id == "ex018"), None)
    if ex018 is None:
        pytest.skip("в каталоге этого разбора нет ex018")
    levels = {z.zone_id: z.role for z in ex018.zones}

    ir = bind_to_recipe(slide(TITLE, BODY), ex018)
    body = next(block for block in ir.blocks if block.block_id == "b")
    title = next(block for block in ir.blocks if block.block_id == "t")

    ladder = list(TypeLevel)
    assert body.zone_id is not None and title.zone_id is not None
    assert ladder.index(levels[body.zone_id]) > ladder.index(levels[title.zone_id]), (
        "тело стоит в ступени не ниже заголовка — лестница перевёрнута"
    )
