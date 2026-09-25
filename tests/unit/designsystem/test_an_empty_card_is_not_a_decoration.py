"""Ряд повторов виден по самому примеру. Change `an-empty-card-is-not-a-decoration`,
таск RG26 (`docs/agents/tasks-24-09.md`).

Прогон на `0833aad`: у рецепта, доставшегося слайду VK Tech, `repeats = 0`, хотя на
слайде-примере стоит сетка одинаковых карточек. Каталог искал ряд только через компонент
шаблона; компонент на этом примере не нашёлся, повторов не стало, и вёрстке было нечего
удалять — `repeat_xml_ids` пуст, пустые карточки уехали в колоду.

Правило: одинаковые фигуры, стоящие по сетке с равным шагом и занятые текстом автора, —
это повтор. Орнамент (пять точек-индикатора, сетка иконок) повтором не становится.

Синтетический манифест проверяет правило на норме и на нарушителе; шаблон кейса —
что оно работает на настоящем файле.
"""

from __future__ import annotations

import pytest

from deckforge.designsystem import derive
from deckforge.domain.template import ComponentKind, ComponentSpec, ShapeKind, TemplateManifest
from deckforge.parsing import TemplateParser
from tests.case_templates import case_template
from tests.unit.designsystem.test_recipes import only, shape, with_example

CARD_CX = 2_400_000
CARD_CY = 1_400_000
TEXT_CY = 300_000


def cards(count: int, *, rows: int = 1, gap: int = 2_800_000, top: int = 3_000_000) -> list:
    """Сетка карточек: плашка и надпись автора внутри каждой."""
    out = []
    for index in range(count):
        column, row = index % (count // rows), index // (count // rows)
        x = 600_000 + column * gap
        y = top + row * (CARD_CY + 400_000)
        out.append(
            shape(f"c{index}", x=x, y=y, cx=CARD_CX, cy=CARD_CY, kind=ShapeKind.SHAPE, text_len=0)
        )
        out.append(
            shape(
                f"t{index}",
                x=x + 100_000,
                y=y + 200_000,
                cx=CARD_CX - 200_000,
                cy=TEXT_CY,
                xml_id=100 + index,
            )
        )
    return out


def test_a_row_of_cards_is_repeats_even_without_a_component(
    manifest: TemplateManifest,
) -> None:
    """Норма: компонента у примера нет, а ряд есть — и каталог его видит."""
    recipe = only(with_example(manifest, cards(3), components=[]))

    assert recipe.repeats == 3
    assert {zone.repeat for zone in recipe.zones if zone.repeat is not None} == {0, 1, 2}
    assert all(row for row in recipe.repeat_xml_ids), "вёрстке нечего будет удалять"


def test_a_grid_is_counted_whole_not_by_its_first_row(manifest: TemplateManifest) -> None:
    """Нарушитель RG26: шесть карточек 3×2, а повторами считался верхний ряд.

    Половину вёрстка заполняла, вторая оставалась пустой и удалить её было нечем:
    в `repeat_xml_ids` её адресов нет.
    """
    recipe = only(with_example(manifest, cards(6, rows=2), components=[]))

    assert recipe.repeats == 6
    assert len(recipe.repeat_xml_ids) == 6
    assert {zone.repeat for zone in recipe.zones if zone.repeat is not None} == {0, 1, 2, 3, 4, 5}


def test_a_row_of_decorations_is_not_repeats(manifest: TemplateManifest) -> None:
    """Нарушитель: пять точек-индикатора по 0,27 см на обложке VK Tech.

    В такую рамку не влезает ни одного знака самым мелким кеглем шаблона: это декор
    автора, а не ряд карточек. Записать их в повторы значило бы обещать вёрстке место
    под текст там, где его нет.
    """
    dots = [
        shape(f"d{i}", x=600_000 + i * 300_000, y=4_000_000, cx=99_124, cy=99_124,
              kind=ShapeKind.SHAPE, text_len=0, size_pt=None)
        for i in range(5)
    ]
    title = shape("title", x=600_000, y=400_000, cx=6_000_000, cy=900_000, size_pt=40.0, xml_id=9)
    body = shape("body", x=600_000, y=1_600_000, cx=6_000_000, cy=900_000, xml_id=10)

    recipe = only(with_example(manifest, [title, body, *dots], components=[]))

    assert recipe.repeats == 0


def test_a_grid_nobody_filled_with_text_is_not_repeats(manifest: TemplateManifest) -> None:
    """Нарушитель: сетка одинаковых плашек, в которых нет ни одной надписи автора.

    Повтор — место под наш текст, и автор сам его текстом занял. Сетка без текста —
    орнамент: у MWS так набраны пятьдесят иконок, у VK Tech пятнадцать.
    """
    icons = [
        shape(f"i{i}", x=600_000 + (i % 4) * 900_000, y=3_000_000 + (i // 4) * 900_000,
              cx=800_000, cy=800_000, kind=ShapeKind.SHAPE, text_len=0, size_pt=None)
        for i in range(8)
    ]
    title = shape("title", x=600_000, y=400_000, cx=6_000_000, cy=900_000, size_pt=40.0, xml_id=9)
    body = shape("body", x=600_000, y=1_600_000, cx=6_000_000, cy=900_000, xml_id=10)

    recipe = only(with_example(manifest, [title, body, *icons], components=[]))

    assert recipe.repeats == 0


def test_shapes_at_random_distances_are_not_a_row(manifest: TemplateManifest) -> None:
    """Нарушитель: три одинаковые надписи, разбросанные по слайду с разным шагом.

    Композиция автора — это равный шаг; случайное сходство размеров рядом не делает.
    """
    scattered = [
        shape("a", x=600_000, y=3_000_000, cx=CARD_CX, cy=TEXT_CY, xml_id=101),
        shape("b", x=3_000_000, y=3_000_000, cx=CARD_CX, cy=TEXT_CY, xml_id=102),
        shape("c", x=7_400_000, y=3_000_000, cx=CARD_CX, cy=TEXT_CY, xml_id=103),
    ]
    title = shape("title", x=600_000, y=400_000, cx=6_000_000, cy=900_000, size_pt=40.0, xml_id=9)

    recipe = only(with_example(manifest, [title, *scattered], components=[]))

    assert recipe.repeats == 0


def test_the_component_of_the_template_still_decides_when_it_is_there(
    manifest: TemplateManifest,
) -> None:
    """Норма: компонент шаблона нашёлся — он и задаёт число повторов.

    Поиск по самому примеру — запасной путь, а не замена: компонент знает про весь
    шаблон, а пример — только про себя.
    """
    width = manifest.slide_size.cx_emu
    tile = ComponentSpec(
        kind=ComponentKind.TILE,
        repeats=3,
        axis="row",
        width_share=CARD_CX / width,
        height_share=CARD_CY / manifest.slide_size.cy_emu,
        gap_share=2_800_000 / width,
        seen_on=[1],
    )

    recipe = only(with_example(manifest, cards(3), components=[tile]))

    assert recipe.repeats == 3


@pytest.mark.parametrize("name", ["VK Tech шаблон.pptx"])
def test_a_real_grid_of_cards_is_seen_whole(name: str) -> None:
    """Замер RG26: у VK Tech `ex017` шесть карточек 3×2 — и столько же повторов.

    Прежде каталог видел ноль, и на слайде оставались шесть пустых карточек.
    """
    manifest = TemplateParser().parse(case_template(name), use_cache=False)
    recipe = next(r for r in derive(manifest).recipes if r.recipe_id == "ex017")

    assert recipe.repeats == 6
    assert len(recipe.repeat_xml_ids) == 6
    assert all(row for row in recipe.repeat_xml_ids), "повтор без адресов вёрстка не удалит"
