"""Каталог компонентов шаблона. Change `design-system-components` (DS3).

Компонент — то, что автор шаблона нарисовал сам и повторил. Признак — не одинаковый
размер (у VK Education 208 одинаковых картинок, и это маркеры списка), а повтор:
три экземпляра и больше с равным шагом.
"""

from __future__ import annotations

import pytest

from deckforge.domain.template import (
    ComponentKind,
    ExampleShape,
    ShapeKind,
    SlideSize,
    TemplateExample,
)
from deckforge.parsing.components import MIN_REPEATS, collect_components
from tests.case_templates import case_template

SIZE = SlideSize(cx_emu=12192000, cy_emu=6858000, aspect="16:9")


def shape(
    x: float, y: float, cx: float, cy: float, *, kind: ShapeKind = ShapeKind.TEXT,
    size_pt: float | None = None, fill: str | None = None, ident: str = "s",
) -> ExampleShape:
    """Фигура в долях слайда — так нагляднее, чем в EMU."""
    return ExampleShape(
        shape_id=ident, kind=kind,
        x=round(x * SIZE.cx_emu), y=round(y * SIZE.cy_emu),
        cx=round(cx * SIZE.cx_emu), cy=round(cy * SIZE.cy_emu),
        size_pt=size_pt, fill_hex=fill, text_len=10,
    )


def example(*shapes: ExampleShape, index: int = 1) -> TemplateExample:
    return TemplateExample(slide_index=index, shapes=list(shapes))


def row_of(count: int, **kwargs: object) -> list[ExampleShape]:
    """Ряд одинаковых плиток с равным шагом."""
    return [
        shape(0.05 + index * 0.3, 0.4, 0.25, 0.2, ident=f"t{index}", **kwargs)  # type: ignore[arg-type]
        for index in range(count)
    ]


def test_three_tiles_in_a_row_are_a_component() -> None:
    found = collect_components([example(*row_of(3))], SIZE)

    assert len(found) == 1
    tile = found[0]
    assert tile.kind is ComponentKind.TILE
    assert tile.repeats == 3
    assert tile.axis == "row"
    assert tile.width_share == pytest.approx(0.25, abs=0.01)
    assert tile.gap_share == pytest.approx(0.30, abs=0.01)
    assert tile.seen_on == [1]


def test_two_tiles_are_not_a_component() -> None:
    """Норма: два одинаковых блока рядом — верстка слайда, а не система."""
    assert collect_components([example(*row_of(MIN_REPEATS - 1))], SIZE) == []


def test_an_uneven_step_is_not_a_repeat() -> None:
    """Норма: три блока, разбросанные как попало, компонентом не считаются."""
    scattered = [
        shape(0.02, 0.4, 0.25, 0.2, ident="a"),
        shape(0.30, 0.4, 0.25, 0.2, ident="b"),
        shape(0.92, 0.4, 0.25, 0.2, ident="c"),
    ]

    assert collect_components([example(*scattered)], SIZE) == []


def test_bullet_markers_are_not_components() -> None:
    """Нарушитель из задания: 208 одинаковых картинок VK Education — это маркеры."""
    markers = [
        shape(0.05, 0.2 + index * 0.05, 0.01, 0.01, kind=ShapeKind.PICTURE, ident=f"m{index}")
        for index in range(6)
    ]

    assert collect_components([example(*markers)], SIZE) == [], "маркер попал в каталог"


def test_parts_of_one_instance_are_one_component() -> None:
    """Картинка, подложка и текст с одним шагом — один компонент, а не три."""
    parts: list[ExampleShape] = []
    for index in range(4):
        top = 0.1 + index * 0.2
        parts.append(shape(0.05, top, 0.03, 0.05, kind=ShapeKind.PICTURE, ident=f"p{index}"))
        parts.append(shape(0.10, top, 0.40, 0.05, ident=f"t{index}", size_pt=18))

    found = collect_components([example(*parts)], SIZE)

    assert len(found) == 1
    component = found[0]
    assert component.kind is ComponentKind.PICTURE_CAPTION
    assert component.parts == [ShapeKind.PICTURE, ShapeKind.TEXT]
    assert component.axis == "column"


def test_a_big_number_over_a_caption_is_a_kpi() -> None:
    parts: list[ExampleShape] = []
    for index in range(3):
        left = 0.05 + index * 0.3
        parts.append(shape(left, 0.3, 0.2, 0.15, ident=f"v{index}", size_pt=44))
        parts.append(shape(left, 0.5, 0.2, 0.08, ident=f"c{index}", size_pt=14))

    found = collect_components([example(*parts)], SIZE)

    assert [item.kind for item in found] == [ComponentKind.KPI]
    assert found[0].text_sizes_pt == [44.0, 14.0]


def test_the_same_component_on_two_slides_is_one_entry() -> None:
    found = collect_components(
        [example(*row_of(3), index=1), example(*row_of(3), index=4)], SIZE
    )

    assert len(found) == 1
    assert found[0].seen_on == [1, 4]


def test_a_template_without_examples_has_an_empty_catalogue() -> None:
    """Холодный шаблон (правило 10): примеров нет — каталог пуст, и это не ошибка."""
    assert collect_components([], SIZE) == []


# --- настоящие шаблоны --------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx", ComponentKind.PICTURE_CAPTION),
        ("Шаблон презентации VK Education.pptx", ComponentKind.TILE),
    ],
)
def test_the_catalogue_of_the_case_templates(name: str, expected: ComponentKind) -> None:
    """Мерило DS3: «картинка + подпись» у WorkSpace и карточка у Education."""
    from deckforge.parsing import TemplateParser

    manifest = TemplateParser().parse(case_template(name), use_cache=False)

    assert manifest.components, f"{name}: каталог пуст"
    assert manifest.component(expected) is not None, f"{name}: нет компонента {expected.value}"
