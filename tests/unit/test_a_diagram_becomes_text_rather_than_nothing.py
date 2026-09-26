"""Блок со словами не пропадает из-за своей формы. Таск RG48,
change `a-diagram-becomes-text-rather-than-nothing`.

Прогон 26.09 после RG43/RG44 закрыл три ошибки структурных слайдов и открыл два новых
источника пустых слайдов.

**Схема как единственное содержание.** WorkSpace s07 и VK Tech s09: модель написала
`smartart` и больше ничего. Зона рецепта — текстовая фигура, рисунок в ней не повторить,
блок снимался, слайд оставался с одним заголовком. При этом слова в схеме есть — её шаги,
и тот же размен давно принят вписыванием по макету (`_smartart_to_bullets`).

**Список при рецепте без зон повтора.** Education s04, рецепт `ex018`: `repeats` больше
нуля, зон с номером повтора нет, `zip` клал ноль пунктов — и список терялся целиком.

Сценарии — из дельты `openspec/changes/a-diagram-becomes-text-rather-than-nothing/`.
"""

from __future__ import annotations

from deckforge.composition.recipe_binding import bind_to_recipe
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.enums import ImageSource, SmartArtPattern, TextRole
from deckforge.domain.slide import (
    BulletItem,
    BulletsBlock,
    ImageBlock,
    KpiBlock,
    KpiItem,
    SlideIR,
    SmartArtBlock,
    TextBlock,
)

STEPS = ["Разбор шаблона", "Извлечение дизайн-системы", "Сборка колоды"]


def zone(zone_id: str, role: TypeLevel, *, chars: int = 200, repeat: int | None = None) -> Zone:
    return Zone(
        zone_id=zone_id, xml_id=int(zone_id[1:]), role=role, repeat=repeat,
        capacity_chars=chars, size_pt=16,
    )


def recipe(*zones: Zone, repeats: int = 0) -> Recipe:
    return Recipe(
        recipe_id="ex004", example_index=4, kind=RecipeKind.TEXT,
        repeats=repeats, zones=list(zones),
    )


def slide_ir(*blocks: object) -> SlideIR:
    return SlideIR(
        slide_id="s07", layout_id="L07", variant="A", blocks=list(blocks)  # type: ignore[arg-type]
    )


def title() -> TextBlock:
    return TextBlock(block_id="b0", role=TextRole.TITLE, text="Пайплайн собирает колоду")


def plain() -> Recipe:
    return recipe(zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY))


# --- слова блока важнее его формы -------------------------------------------------


def test_a_diagram_gives_its_steps_to_the_zone() -> None:
    """Нарушитель: схема — единственное содержание слайда.

    До правки блок снимался, и слайд уезжал в файл с одним заголовком.
    """
    notes: list[str] = []
    diagram = SmartArtBlock(block_id="b1", pattern=SmartArtPattern.PROCESS, items=STEPS)

    bound = bind_to_recipe(slide_ir(title(), diagram), plain(), notes)

    assert len(bound.blocks) == 2, [b.block_id for b in bound.blocks]
    placed = bound.blocks[1].text  # type: ignore[union-attr]
    assert all(step in placed for step in STEPS)
    assert any("не несёт рисунка схемы" in note for note in notes), notes


def test_a_metric_gives_its_value_and_label() -> None:
    """Показатель отдаёт значение с подписью: крупный кегль теряется, числа — нет."""
    notes: list[str] = []
    kpi = KpiBlock(block_id="b1", items=[KpiItem(value="30 %", label="доля рынка")])

    bound = bind_to_recipe(slide_ir(title(), kpi), plain(), notes)

    placed = bound.blocks[1].text  # type: ignore[union-attr]
    assert "30 %" in placed and "доля рынка" in placed


def test_a_block_without_words_is_still_dropped() -> None:
    """Норма: у картинки слов нет — ставить в зону нечего, и снятие названо."""
    notes: list[str] = []
    picture = ImageBlock(block_id="b1", source=ImageSource.ASSET, asset_ref="a1")

    bound = bind_to_recipe(slide_ir(title(), picture), plain(), notes)

    assert [block.block_id for block in bound.blocks] == ["b0"]
    assert any("снят" in note and "image" in note for note in notes), notes


# --- список у рецепта без зон повтора ---------------------------------------------


def test_a_list_survives_a_recipe_that_declares_repeats_without_zones() -> None:
    """Нарушитель: `repeats` больше нуля, зон с номером повтора нет.

    Ветка списка бралась по объявленному числу, `zip` клал ноль пунктов, и блок
    терялся целиком — заметка прогона честно сообщала «повторов в рецепте 0, пунктов 1».
    """
    notes: list[str] = []
    hollow = recipe(zone("z1", TypeLevel.SLIDE_TITLE), zone("z2", TypeLevel.BODY), repeats=3)
    bullets = BulletsBlock(block_id="b1", items=[BulletItem(text="Единственный пункт списка")])

    bound = bind_to_recipe(slide_ir(title(), bullets), hollow, notes)

    assert len(bound.blocks) == 2
    assert not [note for note in notes if "сняты" in note], notes


def test_a_list_still_uses_the_repeat_zones_when_they_exist() -> None:
    """Норма: зоны повторов есть — список раскладывается по ним, как раньше."""
    notes: list[str] = []
    row = recipe(
        zone("z1", TypeLevel.SLIDE_TITLE),
        zone("z2", TypeLevel.BODY, repeat=0),
        zone("z3", TypeLevel.BODY, repeat=1),
        repeats=2,
    )
    bullets = BulletsBlock(
        block_id="b1",
        items=[BulletItem(text="Первый пункт"), BulletItem(text="Второй пункт")],
    )

    bound = bind_to_recipe(slide_ir(title(), bullets), row, notes)

    assert {block.zone_id for block in bound.blocks} == {"z1", "z2", "z3"}
