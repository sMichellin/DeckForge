"""Инварианты рендерера до записи файла и привязка к теме. Change (13) `pptx-writer`."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.dml import MSO_THEME_COLOR

from deckforge.domain.content import Asset, Brief, ContentPackage
from deckforge.domain.enums import ColorRef, FontRef, ImageSource, TextRole
from deckforge.domain.slide import (
    BulletItem,
    BulletsBlock,
    ChartBlock,
    DeckIR,
    FitResult,
    ImageBlock,
    SlideIR,
    TextBlock,
)
from deckforge.domain.template import PlaceholderSpec, TemplateManifest
from deckforge.rendering.images import contain_box, cover_crop
from deckforge.rendering.theme_binding import (
    THEME_COLORS,
    apply_theme_color,
    resolve_font,
    theme_font_token,
)
from deckforge.rendering.writer import PptxWriter, WriterError

# --- theme_binding -----------------------------------------------------------


@pytest.mark.parametrize("ref", list(ColorRef))
def test_every_color_ref_maps_to_the_same_theme_slot(ref: ColorRef) -> None:
    """Слот в XML обязан называться так же, как ссылка в IR: иначе смена темы перекрасит
    объект не в тот цвет."""
    assert MSO_THEME_COLOR.to_xml(THEME_COLORS[ref]) == ref.value


def test_theme_color_is_written_as_scheme_reference_not_rgb() -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(0, 0, 1, 1)
    run = box.text_frame.paragraphs[0].add_run()
    apply_theme_color(run.font, ColorRef.ACCENT2)
    apply_theme_color(box.fill, ColorRef.LT1)
    xml = box._element.xml
    assert '<a:schemeClr val="accent2"/>' in xml
    assert '<a:schemeClr val="lt1"/>' in xml
    assert "srgbClr" not in xml


def test_font_tokens_point_to_the_theme() -> None:
    assert theme_font_token(FontRef.MAJOR_LATIN) == "+mj-lt"
    assert theme_font_token(FontRef.MINOR_LATIN) == "+mn-lt"
    assert theme_font_token(FontRef.MAJOR_CS) == "+mj-cs"
    assert theme_font_token(FontRef.MINOR_CS) == "+mn-cs"


def test_resolve_font_takes_the_family_from_the_manifest(manifest: TemplateManifest) -> None:
    assert resolve_font(FontRef.MAJOR_LATIN, manifest) == manifest.theme.fonts.major_latin
    # Сложной письменности в синтетической теме нет — берётся латинская пара.
    assert resolve_font(FontRef.MINOR_CS, manifest) == manifest.theme.fonts.minor_latin


# --- images: геометрия cover / contain ----------------------------------------


def test_cover_crops_the_long_side_evenly() -> None:
    """Картинка 2:1 в квадрат: срезаем по четверти слева и справа, пропорции целы."""
    assert cover_crop(200, 100, 1000, 1000) == pytest.approx((0.25, 0.0, 0.25, 0.0))


def test_cover_of_a_tall_image_crops_top_and_bottom() -> None:
    assert cover_crop(100, 400, 1000, 1000) == pytest.approx((0.0, 0.375, 0.0, 0.375))


def test_cover_with_matching_aspect_does_not_crop() -> None:
    assert cover_crop(160, 90, 1600, 900) == pytest.approx((0.0, 0.0, 0.0, 0.0))


def test_contain_fits_inside_and_centers() -> None:
    x, y, cx, cy = contain_box(200, 100, 100, 50, 1000, 1000)
    assert (cx, cy) == (1000, 500)
    assert (x, y) == (100, 50 + 250)


# --- validate ----------------------------------------------------------------


def fit(size: float = 18, overflow: bool = False) -> FitResult:
    return FitResult(final_size_pt=size, overflow=overflow)


def title(text: str = "Выручка выросла на 37 %") -> TextBlock:
    return TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text=text)


def ok_slide(**update: object) -> SlideIR:
    base = SlideIR(
        slide_id="s01",
        layout_id="L07",
        variant="A",
        blocks=[
            title(),
            BulletsBlock(block_id="b", placeholder_idx=1, items=[BulletItem(text="пункт")]),
        ],
        fit_report={"t": fit(40), "b": fit(18)},
    )
    return base.model_copy(update=update)


@pytest.fixture
def writer(manifest: TemplateManifest, tmp_path: Path) -> PptxWriter:
    return PptxWriter(tmp_path / "нет-файла.pptx", manifest)


def problems(writer: PptxWriter, slide: SlideIR) -> str:
    with pytest.raises(WriterError) as exc:
        writer.validate(slide)
    return str(exc.value)


def test_valid_slide_passes(writer: PptxWriter) -> None:
    writer.validate(ok_slide())


def test_unknown_layout_is_rejected(writer: PptxWriter) -> None:
    assert "L99" in problems(writer, ok_slide(layout_id="L99"))


def test_empty_slide_is_rejected(writer: PptxWriter) -> None:
    """Слайд без блоков — это пустой фон шаблона в колоде, а не содержание."""
    assert "без блоков" in problems(writer, ok_slide(blocks=[], fit_report={}))


def test_missing_placeholder_is_rejected(writer: PptxWriter) -> None:
    block = TextBlock(block_id="t", placeholder_idx=7, role=TextRole.TITLE, text="а")
    assert "idx=7" in problems(writer, ok_slide(blocks=[block], fit_report={"t": fit(40)}))


def test_text_into_picture_placeholder_is_rejected(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    layout = manifest.layout("L07")
    assert layout is not None
    pic = PlaceholderSpec(idx=9, ph_type="PIC", x=0, y=0, cx=100, cy=100)
    with_pic = manifest.model_copy(
        update={
            "layouts": [
                layout.model_copy(update={"placeholders": [*layout.placeholders, pic]})
                if lay.layout_id == "L07" else lay
                for lay in manifest.layouts
            ]
        }
    )
    block = TextBlock(block_id="x", placeholder_idx=9, role=TextRole.BODY, text="а")
    slide = ok_slide(blocks=[block], fit_report={"x": fit(18)})
    assert "PIC" in problems(PptxWriter(tmp_path / "t.pptx", with_pic), slide)


def test_text_block_without_placeholder_or_coordinates_is_rejected(writer: PptxWriter) -> None:
    block = TextBlock(block_id="x", role=TextRole.BODY, text="а")
    assert "x" in problems(writer, ok_slide(blocks=[block], fit_report={"x": fit(18)}))


def test_coordinates_outside_margins_are_rejected(
    writer: PptxWriter, manifest: TemplateManifest
) -> None:
    block = TextBlock(
        block_id="x", role=TextRole.BODY, text="а",
        x=0, y=0, cx=manifest.slide_size.cx_emu, cy=manifest.slide_size.cy_emu,
    )
    assert "пол" in problems(writer, ok_slide(blocks=[block], fit_report={"x": fit(18)}))


def content_with(tmp_path: Path) -> ContentPackage:
    image = tmp_path / "photo.png"
    Image.new("RGB", (16, 9)).save(image)
    return ContentPackage(
        brief=Brief(purpose="report", audience="команда", target_slides=1),
        assets=[Asset(asset_id="a001", kind="image", path=str(image))],
    )


def test_full_bleed_image_is_allowed(
    writer: PptxWriter, manifest: TemplateManifest, tmp_path: Path
) -> None:
    image = ImageBlock(
        block_id="i", source=ImageSource.ASSET, asset_ref="a001",
        x=0, y=0, cx=manifest.slide_size.cx_emu, cy=manifest.slide_size.cy_emu,
    )
    writer.validate(
        ok_slide(blocks=[title(), image], fit_report={"t": fit(40)}), content_with(tmp_path)
    )


def test_image_without_asset_is_rejected(writer: PptxWriter, manifest: TemplateManifest) -> None:
    content = manifest.content_bbox
    image = ImageBlock(block_id="i", source=ImageSource.ASSET, asset_ref="a001",
                       x=content.x, y=content.y, cx=content.cx, cy=content.cy)
    assert "a001" in problems(writer, ok_slide(blocks=[image], fit_report={}))


def test_generated_image_names_the_change_that_adds_it(
    writer: PptxWriter, manifest: TemplateManifest
) -> None:
    content = manifest.content_bbox
    image = ImageBlock(block_id="i", source=ImageSource.GENERATED, prompt="город",
                       x=content.x, y=content.y, cx=content.cx, cy=content.cy)
    assert "(24)" in problems(writer, ok_slide(blocks=[image], fit_report={}))


def test_image_outside_the_slide_is_rejected(
    writer: PptxWriter, manifest: TemplateManifest, tmp_path: Path
) -> None:
    image = ImageBlock(
        block_id="i", source=ImageSource.ASSET, asset_ref="a001",
        x=1, y=0, cx=manifest.slide_size.cx_emu, cy=manifest.slide_size.cy_emu,
    )
    slide = ok_slide(blocks=[title(), image], fit_report={"t": fit(40)})
    with pytest.raises(WriterError) as exc:
        writer.validate(slide, content_with(tmp_path))
    assert "выходит за слайд" in str(exc.value)


def test_asset_that_is_not_an_image_is_rejected(
    writer: PptxWriter, manifest: TemplateManifest, tmp_path: Path
) -> None:
    content = content_with(tmp_path)
    Path(content.assets[0].path).write_bytes(b"not an image")
    box = manifest.content_bbox
    image = ImageBlock(block_id="i", source=ImageSource.ASSET, asset_ref="a001",
                       x=box.x, y=box.y, cx=box.cx, cy=box.cy)
    slide = ok_slide(blocks=[title(), image], fit_report={"t": fit(40)})
    with pytest.raises(WriterError, match="не картинка"):
        writer.validate(slide, content)


def test_slide_of_a_single_picture_is_rejected(
    writer: PptxWriter, manifest: TemplateManifest, tmp_path: Path
) -> None:
    """C3: слайд из одной картинки — растр, а не редактируемые объекты."""
    box = manifest.content_bbox
    image = ImageBlock(block_id="i", source=ImageSource.ASSET, asset_ref="a001",
                       x=box.x, y=box.y, cx=box.cx, cy=box.cy)
    with pytest.raises(WriterError, match="C3"):
        writer.validate(ok_slide(blocks=[image], fit_report={}), content_with(tmp_path))


def test_empty_text_is_rejected(writer: PptxWriter) -> None:
    """Пустой текст оставил бы на слайде «Введите заголовок»."""
    block = TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="   ")
    assert "пуст" in problems(writer, ok_slide(blocks=[block], fit_report={"t": fit(40)}))


def test_empty_bullets_are_rejected(writer: PptxWriter) -> None:
    block = BulletsBlock(block_id="b", placeholder_idx=1, items=[BulletItem(text=" ")])
    slide = ok_slide(blocks=[title(), block], fit_report={"t": fit(40), "b": fit(18)})
    assert "пуст" in problems(writer, slide)


def test_two_blocks_in_one_placeholder_are_rejected(writer: PptxWriter) -> None:
    second = TextBlock(block_id="t2", placeholder_idx=0, role=TextRole.TITLE, text="Другой")
    slide = ok_slide(blocks=[title(), second], fit_report={"t": fit(40), "t2": fit(40)})
    assert "idx=0" in problems(writer, slide)


def test_placeholder_and_coordinates_together_are_rejected(
    writer: PptxWriter, manifest: TemplateManifest
) -> None:
    """Координаты рядом с плейсхолдером были бы молча проигнорированы."""
    block = TextBlock(
        block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="а",
        x=0, y=0, cx=manifest.slide_size.cx_emu, cy=manifest.slide_size.cy_emu,
    )
    assert "координаты" in problems(writer, ok_slide(blocks=[block], fit_report={"t": fit(40)}))


def test_text_without_fit_report_is_rejected(writer: PptxWriter) -> None:
    """Писатель не пишет слайд, про который не известно, влезает ли текст."""
    assert "fit_report" in problems(writer, ok_slide(fit_report={"t": fit(40)}))


def test_overflow_is_rejected_before_writing(writer: PptxWriter) -> None:
    assert "переполн" in problems(
        writer, ok_slide(fit_report={"t": fit(40), "b": fit(12, overflow=True)})
    )


def test_size_outside_the_template_scale_is_rejected(writer: PptxWriter) -> None:
    assert "13" in problems(writer, ok_slide(fit_report={"t": fit(40), "b": fit(13)}))


def test_unsupported_block_names_the_change_that_adds_it(writer: PptxWriter) -> None:
    chart = ChartBlock(block_id="c", chart_type="clustered_bar", dataset_ref="d1")
    assert "(14)" in problems(writer, ok_slide(blocks=[title(), chart], fit_report={"t": fit(40)}))


def test_all_problems_are_reported_at_once(writer: PptxWriter) -> None:
    message = problems(writer, ok_slide(fit_report={"t": fit(40), "b": fit(13, overflow=True)}))
    assert "13" in message
    assert "переполн" in message


def test_deck_for_another_template_is_rejected_without_creating_a_file(
    writer: PptxWriter, tmp_path: Path
) -> None:
    deck = DeckIR(deck_id="d", variant="A", template_id="sha256:" + "f" * 64, seed=1,
                  slides=[ok_slide()])
    out = tmp_path / "out.pptx"
    with pytest.raises(WriterError, match="template_id"):
        writer.write(deck, out)
    assert not out.exists()


def test_invalid_slide_anywhere_prevents_the_file(
    writer: PptxWriter, manifest: TemplateManifest, tmp_path: Path
) -> None:
    deck = DeckIR(deck_id="d", variant="A", template_id=manifest.template_id, seed=1,
                  slides=[ok_slide(), ok_slide(slide_id="s02", layout_id="L99")])
    out = tmp_path / "out.pptx"
    with pytest.raises(WriterError, match="s02"):
        writer.write(deck, out)
    assert not out.exists()
