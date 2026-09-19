"""Свободное место слайда: сколько его и где оно. Change (25).

Нужно там, где макет не размечен под основной текст. Цифра из этого модуля едет в промпт
композитора, а прямоугольник — в решатель, который блок и поставит. Обе величины обязаны
совпадать: иначе модель получит одно обещание, а блок — другое место.
"""

from __future__ import annotations

from deckforge.composition.free_space import (
    clip,
    effective_capacity,
    free_area,
    free_capacity,
    has_body_slot,
)
from deckforge.domain.base import BBox
from deckforge.domain.template import LayoutSpec, TemplateManifest


def title_only(manifest: TemplateManifest) -> LayoutSpec:
    """Макет с одним плейсхолдером-заголовком — как все пятнадцать у VK WorkSpace."""
    return next(item for item in manifest.layouts if item.capacity.max_chars_body == 0)


def with_body(manifest: TemplateManifest) -> LayoutSpec:
    return next(item for item in manifest.layouts if item.capacity.max_chars_body > 0)


def test_clip_keeps_the_visible_part() -> None:
    area = BBox(x=100, y=100, cx=200, cy=200)
    assert clip(BBox(x=0, y=0, cx=150, cy=150), area) == BBox(x=100, y=100, cx=50, cy=50)


def test_clip_of_a_block_outside_the_area_is_nothing() -> None:
    area = BBox(x=100, y=100, cx=200, cy=200)
    assert clip(BBox(x=0, y=0, cx=50, cy=50), area) is None


def test_has_body_slot_follows_the_capacity(manifest: TemplateManifest) -> None:
    assert has_body_slot(with_body(manifest))
    assert not has_body_slot(title_only(manifest))


def test_free_area_lies_inside_the_content_box(manifest: TemplateManifest) -> None:
    layout = title_only(manifest)
    area = free_area(layout, manifest)
    assert area is not None
    assert manifest.content_bbox.contains(area)


def test_free_area_does_not_overlap_the_title(manifest: TemplateManifest) -> None:
    """Главное свойство: заголовок уже занят, и обещать его место нельзя."""
    layout = title_only(manifest)
    area = free_area(layout, manifest)
    assert area is not None
    for placeholder in layout.placeholders:
        assert area.intersection_area(placeholder.bbox) == 0


def test_a_title_wider_than_the_margins_still_counts_as_taken(
    manifest: TemplateManifest,
) -> None:
    """Заголовок VK WorkSpace шире полей шаблона и начинается выше них.

    Проверка «плейсхолдер целиком внутри области контента» его не видела, и свободным
    объявлялась вся область — вместе с полосой, где лежит заголовок.
    """
    layout = title_only(manifest)
    wide = layout.placeholders[0].model_copy(
        update={"x": 0, "y": 0, "cx": manifest.slide_size.cx_emu}
    )
    stretched = layout.model_copy(update={"placeholders": [wide]})
    area = free_area(stretched, manifest)
    assert area is not None
    assert area.intersection_area(wide.bbox) == 0
    assert area.y >= wide.bbox.bottom


def test_free_capacity_is_not_zero_where_the_layout_says_zero(
    manifest: TemplateManifest,
) -> None:
    """Дефект #62: промпт сообщал «не более 0 знаков», и модель отдавала один заголовок."""
    layout = title_only(manifest)
    assert layout.capacity.max_chars_body == 0
    capacity = free_capacity(layout, manifest)
    assert capacity.max_chars_body > 0
    assert capacity.max_bullets > 0


def test_effective_capacity_leaves_a_proper_layout_alone(manifest: TemplateManifest) -> None:
    """Норма: макет предусмотрел место под текст — считать свободное незачем."""
    layout = with_body(manifest)
    assert effective_capacity(layout, manifest) == layout.capacity


def test_effective_capacity_falls_back_to_free_space(manifest: TemplateManifest) -> None:
    layout = title_only(manifest)
    assert effective_capacity(layout, manifest) == free_capacity(layout, manifest)


def test_capacity_matches_the_area_the_solver_gives(manifest: TemplateManifest) -> None:
    """Обещание промпта и место блока считает один и тот же решатель — это условие."""
    layout = title_only(manifest)
    area = free_area(layout, manifest)
    capacity = free_capacity(layout, manifest)
    assert area is not None
    # Вместимость нулевая только у нулевой площади: связь между числом и местом есть.
    assert (capacity.max_chars_body > 0) == (area.area > 0)
