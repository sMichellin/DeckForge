"""Контракты домена (ARCHITECTURE.md §4). Change (2) `domain-models`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deckforge.domain.base import BBox
from deckforge.domain.enums import ColorRef, ImageSource, TextRole
from deckforge.domain.slide import BulletItem, BulletsBlock, ImageBlock, SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest


def test_manifest_lookups(manifest: TemplateManifest) -> None:
    assert manifest.layout("L07") is not None
    assert manifest.layout("НЕТ ТАКОГО") is None
    assert manifest.typography(TextRole.TITLE).size_pt == 40
    assert manifest.size_ladder_pt == [40.0, 24.0, 18.0, 12.0]


def test_content_bbox_inside_slide(manifest: TemplateManifest) -> None:
    assert manifest.slide_size.bbox.contains(manifest.content_bbox)


def test_manifest_rejects_duplicate_layout_ids(manifest: TemplateManifest) -> None:
    data = manifest.model_dump()
    data["layouts"].append(data["layouts"][0])
    with pytest.raises(ValidationError, match="уникальны"):
        TemplateManifest.model_validate(data)


def test_manifest_rejects_empty_layouts(manifest: TemplateManifest) -> None:
    data = manifest.model_dump()
    data["layouts"] = []
    with pytest.raises(ValidationError):
        TemplateManifest.model_validate(data)


def test_theme_colors_reject_non_hex(manifest: TemplateManifest) -> None:
    data = manifest.model_dump()
    data["theme"]["colors"]["accent1"] = "красный"
    with pytest.raises(ValidationError):
        TemplateManifest.model_validate(data)


def test_slide_ir_discriminates_block_types() -> None:
    slide = SlideIR.model_validate(
        {
            "slide_id": "s05",
            "layout_id": "L07",
            "variant": "A",
            "blocks": [
                {"block_id": "b1", "type": "text", "placeholder_idx": 0,
                 "role": "title", "text": "Выручка выросла на 37 % за год"},
                {"block_id": "b2", "type": "bullets", "placeholder_idx": 1,
                 "items": [{"text": "Первый тезис", "level": 0}]},
            ],
        }
    )
    assert isinstance(slide.blocks[0], TextBlock)
    assert isinstance(slide.blocks[1], BulletsBlock)


def test_slide_ir_accepts_recipe_id_and_zone_id() -> None:
    """slide-recipes: слайд по рецепту несёт recipe_id, блоки — zone_id."""
    slide = SlideIR(
        slide_id="s05",
        layout_id="L07",
        variant="A",
        recipe_id="ex003",
        blocks=[
            TextBlock(block_id="b1", role=TextRole.TITLE, text="Выручка", zone_id="z5"),
            BulletsBlock(
                block_id="b2",
                items=[{"text": "Первый тезис", "level": 0}],
                zone_id="z7",
            ),
        ],
    )
    assert slide.recipe_id == "ex003"
    assert slide.blocks[0].zone_id == "z5"
    assert slide.blocks[1].zone_id == "z7"


def test_slide_ir_recipe_fields_default_to_none() -> None:
    """Старые IR без рецепта читаются без миграции: поля необязательны."""
    slide = SlideIR(
        slide_id="s05",
        layout_id="L07",
        variant="A",
        blocks=[TextBlock(block_id="b1", role=TextRole.TITLE, text="A")],
    )
    assert slide.recipe_id is None
    assert slide.blocks[0].zone_id is None


def test_slide_ir_rejects_duplicate_block_ids() -> None:
    with pytest.raises(ValidationError, match="уникальны"):
        SlideIR(
            slide_id="s01",
            layout_id="L07",
            variant="A",
            blocks=[
                TextBlock(block_id="b1", role=TextRole.TITLE, text="A"),
                TextBlock(block_id="b1", role=TextRole.BODY, text="B"),
            ],
        )


def test_partial_coordinates_are_rejected() -> None:
    """Координаты задаются целиком или не задаются: иначе рендерер не знает, что наследовать."""
    with pytest.raises(ValidationError, match="целиком"):
        TextBlock(block_id="b1", role=TextRole.TITLE, text="A", x=0, y=0)


def test_rgb_literal_is_not_a_valid_color_ref() -> None:
    """C6/ADR-002: цвет в IR — только имя из темы."""
    with pytest.raises(ValidationError):
        TextBlock(block_id="b1", role=TextRole.TITLE, text="A", color_ref="#FF0000")
    assert TextBlock(
        block_id="b1", role=TextRole.TITLE, text="A", color_ref=ColorRef.ACCENT1
    ).color_ref is ColorRef.ACCENT1


def test_image_block_requires_source_payload() -> None:
    with pytest.raises(ValidationError, match="asset_ref"):
        ImageBlock(block_id="b1", source=ImageSource.ASSET)
    with pytest.raises(ValidationError, match="prompt"):
        ImageBlock(block_id="b1", source=ImageSource.GENERATED)


def test_bullets_require_at_least_one_item() -> None:
    with pytest.raises(ValidationError):
        BulletsBlock(block_id="b2", items=[])
    assert BulletsBlock(block_id="b2", items=[BulletItem(text="раз")]).items


def test_bbox_geometry() -> None:
    a = BBox(x=0, y=0, cx=100, cy=100)
    b = BBox(x=50, y=50, cx=100, cy=100)
    assert a.intersection_area(b) == 2500
    assert a.intersection_area(BBox(x=200, y=200, cx=10, cy=10)) == 0
    assert a.contains(BBox(x=10, y=10, cx=10, cy=10))
    assert not a.contains(b)


def test_models_are_frozen() -> None:
    block = TextBlock(block_id="b1", role=TextRole.TITLE, text="A")
    with pytest.raises(ValidationError):
        block.text = "B"  # type: ignore[misc]


def test_extra_fields_are_forbidden() -> None:
    """Модель отдала лишнее поле — значит промпт разошёлся со схемой. Это ошибка, не мусор."""
    with pytest.raises(ValidationError):
        TextBlock(block_id="b1", role=TextRole.TITLE, text="A", неизвестное="что-то")
