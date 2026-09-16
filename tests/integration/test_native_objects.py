"""C3: слайды из нативных редактируемых объектов; смена шаблона перекрашивает колоду.

Change (13) `pptx-writer`. Шаблон — стандартный шаблон самой python-pptx: валидный пакет,
который не принадлежит организаторам и не похож на их шаблоны. Двойник с другой палитрой
собирается подменой цветов темы.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from deckforge.domain.content import Asset, Brief, ContentPackage
from deckforge.domain.enums import ColorRef, ImageFit, ImageSource, LayoutKind, TextRole
from deckforge.domain.slide import (
    BulletItem,
    BulletsBlock,
    DeckIR,
    FitResult,
    ImageBlock,
    SlideIR,
    TextBlock,
)
from deckforge.domain.template import TemplateManifest
from deckforge.parsing import TemplateParser
from deckforge.rendering.writer import PptxWriter, WriterError

TWIN_ACCENT1 = "C2185B"
POTX_CT = "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"
PPTX_CT = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"


def build_template(path: Path, *, sample_slides: int = 2) -> Path:
    """Стандартный шаблон python-pptx со слайдами-примерами, как у настоящих шаблонов."""
    prs = Presentation()
    for _ in range(sample_slides):
        prs.slides.add_slide(prs.slide_layouts[1]).shapes.title.text = "Пример из шаблона"
    prs.save(str(path))
    return path


def rewrite_part(src: Path, dst: Path, part: str, transform: object) -> Path:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == part:
                data = transform(data.decode("utf-8")).encode("utf-8")  # type: ignore[operator]
            zout.writestr(item, data)
    return dst


def recolor_twin(src: Path, dst: Path) -> Path:
    """Тот же шаблон с другим accent1 в теме."""
    return rewrite_part(
        src, dst, "ppt/theme/theme1.xml",
        lambda xml: re.sub(
            r'(<a:accent1>\s*<a:srgbClr val=")[0-9A-Fa-f]{6}', rf"\g<1>{TWIN_ACCENT1}", xml
        ),
    )


def as_potx(src: Path, dst: Path) -> Path:
    return rewrite_part(src, dst, "[Content_Types].xml", lambda xml: xml.replace(PPTX_CT, POTX_CT))


def parse(path: Path, tmp_path: Path) -> TemplateManifest:
    return TemplateParser(cache_dir=tmp_path / "cache").parse(path)


def layout_of(manifest: TemplateManifest, kind: LayoutKind) -> str:
    return manifest.layouts_of_kind(kind)[0].layout_id


def twelve_slides(manifest: TemplateManifest) -> list[SlideIR]:
    """Колода из 12 слайдов: титул, буллеты, две колонки, текст с картинкой."""
    title_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.TITLE)
    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    sub_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.SUBTITLE)
    content = manifest.content_bbox

    slides = [
        SlideIR(
            slide_id="s01", layout_id=layout_of(manifest, LayoutKind.TITLE), variant="A",
            blocks=[
                TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE,
                          text="Выручка выросла на 37 %"),
                TextBlock(block_id="st", placeholder_idx=1, role=TextRole.SUBTITLE,
                          text="Итоги года", color_ref=ColorRef.ACCENT1),
            ],
            speaker_note="Начать с главного вывода.",
            fit_report={
                "t": FitResult(final_size_pt=title_pt),
                "st": FitResult(final_size_pt=sub_pt),
            },
        )
    ]
    for i in range(2, 12):
        slides.append(
            SlideIR(
                slide_id=f"s{i:02d}", layout_id=layout_of(manifest, LayoutKind.BULLETS),
                variant="A",
                blocks=[
                    TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE,
                              text=f"Вывод номер {i}"),
                    BulletsBlock(block_id="b", placeholder_idx=1, items=[
                        BulletItem(text="Первый довод"),
                        BulletItem(text="Подробность", level=1),
                        BulletItem(text="Второй довод"),
                    ]),
                ],
                fit_report={"t": FitResult(final_size_pt=title_pt),
                            "b": FitResult(final_size_pt=body_pt)},
            )
        )
    slides.append(
        SlideIR(
            slide_id="s12", layout_id=layout_of(manifest, LayoutKind.TITLE), variant="A",
            blocks=[
                TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Спасибо"),
                ImageBlock(block_id="img", source=ImageSource.ASSET, asset_ref="a001",
                           fit=ImageFit.COVER, alt_text="Иллюстрация",
                           x=content.x, y=content.y, cx=content.cx // 4, cy=content.cy // 4),
            ],
            fit_report={"t": FitResult(final_size_pt=title_pt)},
        )
    )
    return slides


def content_with_image(tmp_path: Path) -> ContentPackage:
    image = tmp_path / "picture.png"
    Image.new("RGB", (400, 200), "gray").save(image)
    return ContentPackage(
        brief=Brief(purpose="report", audience="команда", target_slides=12),
        assets=[Asset(asset_id="a001", kind="image", path=str(image))],
    )


def deck_for(manifest: TemplateManifest) -> DeckIR:
    return DeckIR(deck_id="d1", variant="A", template_id=manifest.template_id, seed=7,
                  slides=twelve_slides(manifest))


@pytest.fixture
def template(tmp_path: Path) -> Path:
    return build_template(tmp_path / "template.pptx")


@pytest.fixture
def written(template: Path, tmp_path: Path) -> tuple[Path, TemplateManifest]:
    manifest = parse(template, tmp_path)
    out = PptxWriter(template, manifest).write(
        deck_for(manifest), tmp_path / "deck.pptx", content=content_with_image(tmp_path)
    )
    return out, manifest


def slide_xml(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        return {
            n: z.read(n).decode("utf-8")
            for n in z.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
        }


def test_every_slide_has_editable_objects(written: tuple[Path, TemplateManifest]) -> None:
    out, _ = written
    prs = Presentation(str(out))
    assert len(prs.slides) == 12
    for slide in prs.slides:
        shapes = list(slide.shapes)
        assert shapes, "пустой слайд"
        pictures = [s for s in shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
        assert len(pictures) < len(shapes), "слайд из одной картинки нарушает C3"
        assert any(s.has_text_frame and s.text_frame.text for s in shapes)


def test_sample_slides_of_the_template_are_dropped(written: tuple[Path, TemplateManifest]) -> None:
    out, _ = written
    texts = [s.text_frame.text for slide in Presentation(str(out)).slides
             for s in slide.shapes if s.has_text_frame]
    assert "Пример из шаблона" not in texts


def test_slides_use_the_layouts_named_in_ir(written: tuple[Path, TemplateManifest]) -> None:
    out, manifest = written
    for ir, slide in zip(deck_for(manifest).slides, Presentation(str(out)).slides, strict=True):
        spec = manifest.layout(ir.layout_id)
        assert spec is not None
        assert slide.slide_layout.name.strip() == spec.name


def test_text_goes_into_placeholders_with_levels_and_sizes(
    written: tuple[Path, TemplateManifest],
) -> None:
    out, manifest = written
    slide = Presentation(str(out)).slides[1]
    body = slide.placeholders[1]
    paragraphs = body.text_frame.paragraphs
    assert [p.text for p in paragraphs] == ["Первый довод", "Подробность", "Второй довод"]
    assert [p.level for p in paragraphs] == [0, 1, 0]
    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    assert all(r.font.size.pt == body_pt for p in paragraphs for r in p.runs)


def test_no_literal_colors_in_slides(written: tuple[Path, TemplateManifest]) -> None:
    out, _ = written
    xml = slide_xml(out)
    assert xml
    assert not any("srgbClr" in part for part in xml.values())
    assert any('<a:schemeClr val="accent1"/>' in part for part in xml.values())


def test_unfilled_placeholders_are_removed(written: tuple[Path, TemplateManifest]) -> None:
    out, _ = written
    for slide in Presentation(str(out)).slides:
        for ph in slide.placeholders:
            assert ph.has_text_frame is False or ph.text_frame.text, "пустой плейсхолдер"


def test_image_keeps_aspect_and_alt_text(written: tuple[Path, TemplateManifest]) -> None:
    out, _ = written
    picture = next(s for s in Presentation(str(out)).slides[11].shapes
                   if s.shape_type == MSO_SHAPE_TYPE.PICTURE)
    # Показанная часть — это исходник 2:1, обрезанный, но не растянутый.
    image_ratio = 2.0
    shown_ratio = (picture.width / (1 - picture.crop_left - picture.crop_right)) / (
        picture.height / (1 - picture.crop_top - picture.crop_bottom)
    )
    assert shown_ratio == pytest.approx(image_ratio, rel=1e-3)
    assert picture._element.nvPicPr.cNvPr.get("descr") == "Иллюстрация"


def test_speaker_note_is_written(written: tuple[Path, TemplateManifest]) -> None:
    out, _ = written
    slide = Presentation(str(out)).slides[0]
    assert slide.notes_slide.notes_text_frame.text == "Начать с главного вывода."


def reverse_layout_rels(src: Path, dst: Path) -> Path:
    """Связи мастера на макеты в обратном порядке: парсер обходит `.rels`, python-pptx —
    `sldLayoutIdLst`, и на настоящих шаблонах эти порядки расходятся."""

    def transform(xml: str) -> str:
        rels = re.findall(r"<Relationship [^>]*/>", xml)
        layouts = [r for r in rels if "slideLayout" in r]
        others = [r for r in rels if "slideLayout" not in r]
        body = "".join(others + layouts[::-1])
        return re.sub(
            r"(<Relationships[^>]*>).*(</Relationships>)",
            lambda m: m.group(1) + body + m.group(2),
            xml,
            flags=re.S,
        )

    return rewrite_part(src, dst, "ppt/slideMasters/_rels/slideMaster1.xml.rels", transform)


def test_layouts_are_found_by_part_not_by_position(template: Path, tmp_path: Path) -> None:
    """`prs.slide_layouts[index]` ошибается, когда порядок связей мастера не совпадает
    со списком макетов, а парсер пропустил макет без плейсхолдеров (здесь — пустой)."""
    shuffled = reverse_layout_rels(template, tmp_path / "shuffled.pptx")
    manifest = parse(shuffled, tmp_path)
    prs = Presentation(str(shuffled))
    assert any(
        spec.index >= len(prs.slide_layouts) or prs.slide_layouts[spec.index].name != spec.name
        for spec in manifest.layouts
    ), "шаблон теста обязан ломать наивное сопоставление по позиции"

    title_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.TITLE)
    slides = [
        SlideIR(
            slide_id=f"s{i:02d}", layout_id=spec.layout_id, variant="A",
            blocks=[TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE,
                              text=spec.name)],
            fit_report={"t": FitResult(final_size_pt=title_pt)},
        )
        for i, spec in enumerate(manifest.layouts)
        if spec.placeholder(0) is not None
    ]
    deck = DeckIR(deck_id="d", variant="A", template_id=manifest.template_id, seed=1,
                  slides=slides)
    out = PptxWriter(shuffled, manifest).write(deck, tmp_path / "deck.pptx")
    for ir, slide in zip(slides, Presentation(str(out)).slides, strict=True):
        spec = manifest.layout(ir.layout_id)
        assert spec is not None
        assert slide.slide_layout.name.strip() == spec.name


SECTION_EXT = (
    '<p:extLst><p:ext uri="{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"><p14:sec'
    'tionLst xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010'
    '/main"><p14:section name="Примеры" id="{11111111-2222-3333-4444-555555'
    '555555}"><p14:sldIdLst>{section}</p14:sldIdLst></p14:section></p14:sec'
    'tionLst></p:ext></p:extLst>'
)


def add_sections_and_custom_show(src: Path, dst: Path) -> Path:
    """Разделы и произвольный показ, ссылающиеся на слайды-примеры шаблона."""

    def transform(xml: str) -> str:
        ids = re.findall(r'<p:sldId id="(\d+)" r:id="(rId\d+)"/>', xml)
        show = "".join(f'<p:sld r:id="{rid}"/>' for _, rid in ids)
        section = "".join(f'<p14:sldId id="{sid}"/>' for sid, _ in ids)
        custom = (
            '<p:custShowLst><p:custShow name="Показ" id="0">'
            f"<p:sldLst>{show}</p:sldLst></p:custShow></p:custShowLst>"
        )
        xml = xml.replace("<p:defaultTextStyle>", custom + "<p:defaultTextStyle>")
        return xml.replace("</p:presentation>",
                           SECTION_EXT.replace("{section}", section) + "</p:presentation>")

    return rewrite_part(src, dst, "ppt/presentation.xml", transform)


def test_sample_slides_leave_no_references_behind(template: Path, tmp_path: Path) -> None:
    rich = add_sections_and_custom_show(template, tmp_path / "rich.pptx")
    with zipfile.ZipFile(rich) as z:
        source = z.read("ppt/presentation.xml").decode("utf-8")
    assert "custShowLst" in source
    assert "sectionLst" in source
    manifest = parse(rich, tmp_path)
    out = PptxWriter(rich, manifest).write(deck_for(manifest), tmp_path / "deck.pptx",
                                           content=content_with_image(tmp_path))
    with zipfile.ZipFile(out) as z:
        presentation = z.read("ppt/presentation.xml").decode("utf-8")
        slide_parts = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
    assert "custShowLst" not in presentation
    assert "sectionLst" not in presentation
    assert len(slide_parts) == 12


def test_missing_alt_text_does_not_leak_the_file_name(template: Path, tmp_path: Path) -> None:
    manifest = parse(template, tmp_path)
    deck = deck_for(manifest)
    last = deck.slides[-1]
    blocks = [b.model_copy(update={"alt_text": None}) if isinstance(b, ImageBlock) else b
              for b in last.blocks]
    deck = deck.model_copy(
        update={"slides": [*deck.slides[:-1], last.model_copy(update={"blocks": blocks})]}
    )
    out = PptxWriter(template, manifest).write(deck, tmp_path / "deck.pptx",
                                               content=content_with_image(tmp_path))
    picture = next(s for s in Presentation(str(out)).slides[11].shapes
                   if s.shape_type == MSO_SHAPE_TYPE.PICTURE)
    assert "picture.png" not in (picture._element.nvPicPr.cNvPr.get("descr") or "")


def test_switching_the_template_recolors_the_deck_without_code_changes(
    template: Path, tmp_path: Path
) -> None:
    """Главный аргумент ADR-002: тот же IR на другом шаблоне — другая палитра,
    а разметка слайдов байт в байт та же."""
    twin = recolor_twin(template, tmp_path / "twin.pptx")
    manifest, twin_manifest = parse(template, tmp_path), parse(twin, tmp_path)
    assert twin_manifest.theme.colors.accent1 == f"#{TWIN_ACCENT1}"
    assert manifest.theme.colors.accent1 != twin_manifest.theme.colors.accent1

    content = content_with_image(tmp_path)
    first = PptxWriter(template, manifest).write(deck_for(manifest), tmp_path / "a.pptx",
                                                 content=content)
    twin_deck = deck_for(manifest).model_copy(update={"template_id": twin_manifest.template_id})
    second = PptxWriter(twin, twin_manifest).write(twin_deck, tmp_path / "b.pptx",
                                                   content=content)

    assert slide_xml(first) == slide_xml(second)
    assert parse(second, tmp_path).theme.colors.accent1 == f"#{TWIN_ACCENT1}"


def test_potx_template_is_accepted(template: Path, tmp_path: Path) -> None:
    potx = as_potx(template, tmp_path / "template.potx")
    manifest = parse(potx, tmp_path)
    deck = deck_for(manifest)
    out = PptxWriter(potx, manifest).write(deck, tmp_path / "deck.pptx",
                                           content=content_with_image(tmp_path))
    with zipfile.ZipFile(out) as z:
        assert PPTX_CT in z.read("[Content_Types].xml").decode("utf-8")
    assert len(Presentation(str(out)).slides) == 12


def test_manifest_from_another_file_is_caught_by_layout_names(
    template: Path, tmp_path: Path
) -> None:
    """Если манифест снят не с этого файла, писатель падает, а не кладёт слайд на чужой макет."""
    manifest = parse(template, tmp_path)
    renamed = manifest.model_copy(
        update={"layouts": [lay.model_copy(update={"name": f"Чужой {lay.name}"})
                            for lay in manifest.layouts]}
    )
    with pytest.raises(WriterError, match="макет"):
        PptxWriter(template, renamed).write(deck_for(renamed), tmp_path / "x.pptx",
                                            content=content_with_image(tmp_path))
