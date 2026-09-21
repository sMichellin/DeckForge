"""Рисуем компонентом шаблона, когда он есть. Change `draw-with-the-template-component` (DS4).

Пропорции плитки и отношение кегля значения к подписи — вопрос дизайна, а не вкуса.
Каталог компонентов (DS3) отвечает на него числами из самого шаблона: у VK WorkSpace
показатель набран 66 pt над 20 pt, у VK Education — 36 над 16. Нет компонента —
раскладка прежняя, та, что была до DS4.
"""

from __future__ import annotations

import pytest

from deckforge.domain.base import BBox
from deckforge.domain.enums import SmartArtPattern
from deckforge.domain.template import ComponentKind, ComponentSpec, ShapeKind
from deckforge.domain.units import EMU_PER_CM
from deckforge.layout.diagram import diagram_geometry

BOX = BBox(x=0, y=0, cx=24 * EMU_PER_CM, cy=10 * EMU_PER_CM)


def tile(*, width: float, height: float, gap: float, axis: str = "row") -> ComponentSpec:
    return ComponentSpec(
        kind=ComponentKind.TILE, repeats=3, axis=axis,
        width_share=width, height_share=height, gap_share=gap,
        parts=[ShapeKind.TEXT], seen_on=[1],
    )


def test_without_a_component_the_layout_is_the_old_one() -> None:
    """Норма: шаблон молчит — сетка та же, что была до DS4."""
    plain = diagram_geometry(SmartArtPattern.MATRIX, 4, BOX)
    same = diagram_geometry(SmartArtPattern.MATRIX, 4, BOX, None)

    assert [node.cx for node in plain.nodes] == [node.cx for node in same.nodes]
    assert [node.cy for node in plain.nodes] == [node.cy for node in same.nodes]


def test_a_wide_template_tile_makes_wide_tiles() -> None:
    """Шаблон рисует плитку вдвое шире своей высоты — и наша становится такой же."""
    plain = diagram_geometry(SmartArtPattern.MATRIX, 4, BOX)
    wide = diagram_geometry(
        SmartArtPattern.MATRIX, 4, BOX, tile(width=0.30, height=0.15, gap=0.33)
    )

    assert wide.nodes[0].cy < plain.nodes[0].cy, "плитка не стала площе"
    assert wide.nodes[0].cx / wide.nodes[0].cy == pytest.approx(2.0, rel=0.25)


def test_the_gap_of_the_template_is_used() -> None:
    """Зазор — это шаг между экземплярами минус сам экземпляр."""
    tight = diagram_geometry(
        SmartArtPattern.MATRIX, 3, BOX, tile(width=0.30, height=0.30, gap=0.31)
    )
    loose = diagram_geometry(
        SmartArtPattern.MATRIX, 3, BOX, tile(width=0.30, height=0.30, gap=0.45)
    )

    tight_gap = tight.nodes[1].x - (tight.nodes[0].x + tight.nodes[0].cx)
    loose_gap = loose.nodes[1].x - (loose.nodes[0].x + loose.nodes[0].cx)
    assert loose_gap > tight_gap, "зазор шаблона не дошёл до сетки"


def test_a_nonsense_gap_falls_back_to_ours() -> None:
    """Повтор с одного слайда даёт шаг меньше экземпляра: такой зазор сузил бы сетку в ноль."""
    plain = diagram_geometry(SmartArtPattern.MATRIX, 3, BOX)
    overlapping = diagram_geometry(
        SmartArtPattern.MATRIX, 3, BOX, tile(width=0.40, height=0.30, gap=0.20)
    )

    assert [n.cx for n in overlapping.nodes] == [n.cx for n in plain.nodes]


def test_a_kpi_component_does_not_change_tiles() -> None:
    """Норма: плитку задаёт плитка. Показатель к сетке отношения не имеет."""
    kpi = ComponentSpec(
        kind=ComponentKind.KPI, repeats=3, axis="row",
        width_share=0.2, height_share=0.25, gap_share=0.24,
        text_sizes_pt=[66.0, 20.0], parts=[ShapeKind.TEXT], seen_on=[1],
    )
    plain = diagram_geometry(SmartArtPattern.MATRIX, 3, BOX)

    assert [n.cx for n in diagram_geometry(SmartArtPattern.MATRIX, 3, BOX, kpi).nodes] == [
        n.cx for n in plain.nodes
    ]


# --- кегль подписи показателя -------------------------------------------------


def test_the_caption_size_follows_the_template_ratio(manifest: object) -> None:
    """У шаблона значение вчетверо крупнее подписи — подпись уходит вниз по шкале."""
    from deckforge.rendering.writer import _label_size_pt

    kpi = ComponentSpec(
        kind=ComponentKind.KPI, repeats=3, axis="row",
        width_share=0.2, height_share=0.25, gap_share=0.24,
        text_sizes_pt=[66.0, 20.0], parts=[ShapeKind.TEXT], seen_on=[1],
    )
    with_kpi = manifest.model_copy(update={"components": [kpi]})  # type: ignore[attr-defined]
    value_pt = max(with_kpi.size_ladder_pt)

    size = _label_size_pt(with_kpi, value_pt, None, value_pt)

    assert size in with_kpi.size_ladder_pt, "кегль вне шкалы шаблона (правило 6)"
    assert size < value_pt, "подпись не стала мельче значения"


def test_without_a_kpi_component_the_caption_keeps_its_role_size(manifest: object) -> None:
    """Норма: шаблон о показателе ничего не сказал — кегль роли, как было."""
    from deckforge.domain.enums import TextRole
    from deckforge.rendering.writer import _label_size_pt

    caption = manifest.typography(TextRole.CAPTION)  # type: ignore[attr-defined]
    assert caption is not None

    size = _label_size_pt(manifest, max(manifest.size_ladder_pt), caption, 12.0)  # type: ignore[attr-defined]

    assert size == caption.size_pt
