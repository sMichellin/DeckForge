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

from deckforge.domain.content import Asset, Brief, ContentPackage, Dataset, Series
from deckforge.domain.enums import (
    ChartType,
    ColorRef,
    ImageFit,
    ImageSource,
    LayoutKind,
    TextRole,
)
from deckforge.domain.rules import readable_text_ref
from deckforge.domain.slide import (
    BulletItem,
    BulletsBlock,
    ChartBlock,
    DeckIR,
    FitResult,
    IconBlock,
    ImageBlock,
    KpiBlock,
    KpiItem,
    SlideIR,
    SmartArtBlock,
    TableBlock,
    TextBlock,
)
from deckforge.domain.template import TemplateManifest
from deckforge.layout.fitting import fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.parsing import TemplateParser
from deckforge.rendering.writer import PptxWriter, WriterError
from tests.unit.test_layout_fonts import make_font

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


# --- change (14): диаграммы, таблицы, KPI ------------------------------------------


def chart_content(tmp_path: Path, *series: Series) -> ContentPackage:
    return content_with_image(tmp_path).model_copy(update={"datasets": [Dataset(
        dataset_id="d001", title="Выручка", categories=["2024", "2025", "2026"],
        series=list(series) or [Series(name="Россия", values=[1.0, 2.0, 3.0]),
                                Series(name="СНГ", values=[0.5, 0.7, 0.9])],
        unit="млн ₽",
    )]})


def theme_fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    """Синтетические гарнитуры темы: вписывание подменённых блоков детерминировано."""
    directory = tmp_path / "fonts"
    directory.mkdir(exist_ok=True)
    for family in {manifest.theme.fonts.major_latin, manifest.theme.fonts.minor_latin}:
        make_font(directory, family, advance=500)
        make_font(directory, family, advance=550, bold=True)
    return FontLibrary([directory])


def visual_deck(manifest: TemplateManifest, *blocks: object) -> DeckIR:
    title_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.TITLE)
    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    sub_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.SUBTITLE)
    report = {"t": FitResult(final_size_pt=title_pt)}
    for block in blocks:
        if isinstance(block, TableBlock):
            report[block.block_id] = FitResult(final_size_pt=body_pt)
        elif isinstance(block, KpiBlock):
            report[block.block_id] = FitResult(final_size_pt=sub_pt)
    slide = SlideIR(
        slide_id="s01", layout_id=layout_of(manifest, LayoutKind.TITLE), variant="A",
        blocks=[TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE,
                          text="Выручка выросла"), *blocks],  # type: ignore[list-item]
        fit_report=report,
    )
    return DeckIR(deck_id="d", variant="A", template_id=manifest.template_id, seed=1,
                  slides=[slide])


def region(manifest: TemplateManifest, part: int, of: int) -> dict[str, int]:
    box = manifest.content_bbox
    height = box.cy // of
    return {"x": box.x, "y": box.y + part * height, "cx": box.cx, "cy": height}


def chart_parts(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()
                if re.fullmatch(r"ppt/charts/chart\d+\.xml", n)}


def test_chart_table_and_kpi_are_native_objects(template: Path, tmp_path: Path) -> None:
    manifest = parse(template, tmp_path)
    deck = visual_deck(
        manifest,
        ChartBlock(block_id="c", chart_type=ChartType.CLUSTERED_COLUMN, dataset_ref="d001",
                   **region(manifest, 1, 4)),
        TableBlock(block_id="tb", dataset_ref="d001", **region(manifest, 2, 4)),
        KpiBlock(block_id="k", items=[KpiItem(value="37 %", label="рост"),
                                      KpiItem(value="×2", label="клиенты")],
                 **region(manifest, 3, 4)),
    )
    out = PptxWriter(template, manifest).write(deck, tmp_path / "deck.pptx",
                                               content=chart_content(tmp_path))
    shapes = list(Presentation(str(out)).slides[0].shapes)
    assert sum(1 for s in shapes if s.has_chart) == 1
    assert sum(1 for s in shapes if s.has_table) == 1
    texts = [s.text_frame.text for s in shapes if s.has_text_frame]
    # Число и процент — неразрывно (Т4, `no-hanging-prepositions`).
    assert "37 %\nрост" in texts
    table = next(s for s in shapes if s.has_table).table
    assert [c.text for c in table.rows[1].cells] == ["2024", "1", "0,5"]
    assert not any("srgbClr" in xml for xml in [*slide_xml(out).values(),
                                               *chart_parts(out).values()])


def test_switching_the_template_recolors_the_chart(template: Path, tmp_path: Path) -> None:
    """Критерий change (14): диаграмма меняет палитру вместе с шаблоном без правки кода."""
    twin = recolor_twin(template, tmp_path / "twin.pptx")
    manifest, twin_manifest = parse(template, tmp_path), parse(twin, tmp_path)
    chart = ChartBlock(block_id="c", chart_type=ChartType.CLUSTERED_COLUMN, dataset_ref="d001",
                       **region(manifest, 1, 2))
    content = chart_content(tmp_path)
    first = PptxWriter(template, manifest).write(
        visual_deck(manifest, chart), tmp_path / "a.pptx", content=content)
    twin_deck = visual_deck(manifest, chart).model_copy(
        update={"template_id": twin_manifest.template_id})
    second = PptxWriter(twin, twin_manifest).write(twin_deck, tmp_path / "b.pptx",
                                                   content=content)
    assert chart_parts(first) == chart_parts(second)
    assert '<a:schemeClr val="accent1"/>' in next(iter(chart_parts(first).values()))
    assert parse(second, tmp_path).theme.colors.accent1 == f"#{TWIN_ACCENT1}"


def test_impossible_chart_degrades_to_a_table(template: Path, tmp_path: Path) -> None:
    manifest = parse(template, tmp_path)
    pie = ChartBlock(block_id="c", chart_type=ChartType.PIE, dataset_ref="d001",
                     **region(manifest, 1, 2))
    writer = PptxWriter(template, manifest, fonts=theme_fonts(tmp_path, manifest))
    out = writer.write(visual_deck(manifest, pie), tmp_path / "deck.pptx",
                       content=chart_content(tmp_path))
    shapes = list(Presentation(str(out)).slides[0].shapes)
    assert not any(s.has_chart for s in shapes)
    assert any(s.has_table for s in shapes)
    assert writer.degradations == ["s01/c: диаграмма → таблица (у круговой диаграммы должна "
                                   "быть одна серия)"]


def test_table_that_does_not_fit_degrades_to_bullets(template: Path, tmp_path: Path) -> None:
    """Кольцевая с отрицательной долей → таблица из 21 строки не влезает ни при каком кегле
    шкалы → 20 коротких буллетов влезают."""
    manifest = parse(template, tmp_path)
    categories = [f"к{i}" for i in range(20)]
    content = content_with_image(tmp_path).model_copy(update={"datasets": [Dataset(
        dataset_id="d001", title="Доли", categories=categories,
        series=[Series(name="Доля", values=[-1.0] + [1.0] * 19)],
    )]})
    ring = ChartBlock(block_id="c", chart_type=ChartType.DOUGHNUT, dataset_ref="d001",
                      **region(manifest, 1, 2))
    writer = PptxWriter(template, manifest, fonts=theme_fonts(tmp_path, manifest))
    out = writer.write(visual_deck(manifest, ring), tmp_path / "deck.pptx", content=content)
    shapes = list(Presentation(str(out)).slides[0].shapes)
    assert not any(s.has_chart or s.has_table for s in shapes)
    bullets = next(s for s in shapes if s.has_text_frame and "к0:" in s.text_frame.text)
    assert [p.text for p in bullets.text_frame.paragraphs][:2] == ["к0: -1", "к1: 1"]
    assert [d.split(": ", 1)[1].split(" (")[0] for d in writer.degradations] == [
        "диаграмма → таблица", "таблица → буллеты"]


def test_table_takes_the_template_default_style(template: Path, tmp_path: Path) -> None:
    style = "{073A0DAA-6AF3-43AB-8588-CEC1D06C72B9}"
    styled = rewrite_part(template, tmp_path / "styled.pptx", "ppt/tableStyles.xml",
                          lambda xml: re.sub(r'def="\{[^}]+\}"', f'def="{style}"', xml))
    manifest = parse(styled, tmp_path)
    table = TableBlock(block_id="tb", header=["Год", "Выручка"], rows=[["2025", "2"]],
                       **region(manifest, 1, 2))
    out = PptxWriter(styled, manifest).write(visual_deck(manifest, table),
                                             tmp_path / "deck.pptx")
    assert any(f"<a:tableStyleId>{style}</a:tableStyleId>" in xml
               for xml in slide_xml(out).values())


def dark_title_layout(src: Path, dst: Path) -> Path:
    """Макет, где заголовок светлый по ссылке на тему — как тёмные макеты шаблонов кейса,
    у которых фон тёмный, а `clrMap` не переопределён."""
    light = (
        "<a:lstStyle><a:lvl1pPr><a:defRPr><a:solidFill><a:schemeClr val=\"lt1\"/>"
        "</a:solidFill></a:defRPr></a:lvl1pPr></a:lstStyle>"
    )
    return rewrite_part(src, dst, "ppt/slideLayouts/slideLayout1.xml",
                        lambda xml: xml.replace("<a:lstStyle/>", light, 1))


def test_free_text_inherits_the_layout_text_color(template: Path, tmp_path: Path) -> None:
    """Цвет роли из типошкалы на тёмном макете дал бы тёмный текст на тёмном фоне."""
    dark = dark_title_layout(template, tmp_path / "dark.pptx")
    manifest = parse(dark, tmp_path)
    assert manifest.layout(layout_of(manifest, LayoutKind.TITLE)) is not None
    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    box = region(manifest, 1, 2)
    deck = visual_deck(
        manifest,
        KpiBlock(block_id="k", items=[KpiItem(value="37 %", label="рост")],
                 **region(manifest, 1, 2)),
    )
    note = TextBlock(block_id="n", role=TextRole.BODY, text="Сноска",
                     **{**box, "y": box["y"] + box["cy"] // 2, "cy": box["cy"] // 2})
    slide = deck.slides[0]
    deck = deck.model_copy(update={"slides": [slide.model_copy(update={
        "blocks": [*slide.blocks, note],
        "fit_report": {**slide.fit_report, "n": FitResult(final_size_pt=body_pt)},
    })]})
    out = PptxWriter(dark, manifest).write(deck, tmp_path / "deck.pptx")
    shapes = {s.text_frame.text: s for s in Presentation(str(out)).slides[0].shapes
              if s.has_text_frame and s.shape_type == MSO_SHAPE_TYPE.TEXT_BOX}
    label_xml = shapes["37 %\nрост"]._element.xml
    assert label_xml.count('<a:schemeClr val="lt1"/>') == 1, "подпись — цветом текста макета"
    assert '<a:schemeClr val="accent1"/>' in label_xml, "значение — акцентом"
    assert '<a:schemeClr val="lt1"/>' in shapes["Сноска"]._element.xml


def dark_background_layout(src: Path, dst: Path) -> Path:
    """Макет, залитый тёмным слотом темы, у которого цвет текста не задан нигде.

    Так выглядят все 15 макетов VK WorkSpace: фон `dk1`, а плейсхолдеры цвет не объявляют.
    Свободной фигуре на таком макете наследовать цвет не от чего.
    """
    bg = (
        '<p:bg><p:bgPr><a:solidFill><a:schemeClr val="dk1"/></a:solidFill>'
        "<a:effectLst/></p:bgPr></p:bg>"
    )
    return rewrite_part(
        src, dst, "ppt/slideLayouts/slideLayout1.xml",
        lambda xml: re.sub(r"(<p:cSld[^>]*>)", rf"\g<1>{bg}", xml, count=1),
    )


def test_every_layout_gets_a_background(template: Path, tmp_path: Path) -> None:
    """Фон описан у каждого макета, иначе проверка контраста снова меряет догадку.

    У стандартного шаблона python-pptx `p:bg` не объявлен нигде — это и есть случай,
    когда манифест обязан сказать «фона в шаблоне нет», а не промолчать.
    """
    manifest = parse(template, tmp_path)
    assert manifest.layouts
    for layout in manifest.layouts:
        assert layout.background is not None, layout.name
        assert layout.background.source in {"layout", "master", "picture", "theme"}
        assert layout.background.color_hex.startswith("#")


def test_free_text_is_readable_on_a_dark_layout(template: Path, tmp_path: Path) -> None:
    """Дефект 19.09: свободный текст на тёмном макете выходил чёрным, то есть невидимым.

    Текстбокс в OOXML не наследует цвет ни от кого — плейсхолдера-родителя у него нет.
    Цвет роли из типошкалы здесь не спасает: он выведен из плейсхолдеров шаблона и на
    тёмном макете тоже тёмный. Цвет выбирается по фону макета, измерением контраста,
    поэтому правило работает и на незнакомом шаблоне.
    """
    dark = dark_background_layout(template, tmp_path / "dark.pptx")
    manifest = parse(dark, tmp_path)
    title_layout = manifest.layout(layout_of(manifest, LayoutKind.TITLE))
    assert title_layout is not None and title_layout.background is not None
    assert title_layout.background.color_ref is ColorRef.DK1

    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    note = TextBlock(block_id="n", role=TextRole.BODY, text="Сноска", **region(manifest, 1, 2))
    deck = visual_deck(manifest)
    slide = deck.slides[0]
    deck = deck.model_copy(update={"slides": [slide.model_copy(update={
        "blocks": [*slide.blocks, note],
        "fit_report": {**slide.fit_report, "n": FitResult(final_size_pt=body_pt)},
    })]})

    out = PptxWriter(dark, manifest).write(deck, tmp_path / "deck.pptx")
    written = next(
        s for s in Presentation(str(out)).slides[0].shapes
        if s.has_text_frame and s.text_frame.text == "Сноска"
    )
    xml = written._element.xml
    readable = readable_text_ref(manifest, title_layout.background.color_hex)
    assert readable is not ColorRef.DK1, "на тёмном фоне тёмный слот читаться не может"
    assert f'<a:schemeClr val="{readable.value}"/>' in xml
    # Ссылка на тему, а не RGB: смена шаблона обязана перекрашивать колоду (ADR-002).
    assert "<a:srgbClr" not in xml


def test_free_text_keeps_the_layout_color_when_the_template_named_one(
    template: Path, tmp_path: Path
) -> None:
    """Норма к той же правке: решение автора шаблона главнее измерения.

    Макет тёмный **и** называет цвет текста — берётся названный, фон в выборе
    не участвует. Иначе правка перекрашивала бы шаблоны, которые всё сделали правильно.
    """
    dark = dark_background_layout(template, tmp_path / "dark.pptx")
    styled = dark_title_layout(dark, tmp_path / "styled.pptx")
    manifest = parse(styled, tmp_path)
    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    note = TextBlock(block_id="n", role=TextRole.BODY, text="Сноска", **region(manifest, 1, 2))
    deck = visual_deck(manifest)
    slide = deck.slides[0]
    deck = deck.model_copy(update={"slides": [slide.model_copy(update={
        "blocks": [*slide.blocks, note],
        "fit_report": {**slide.fit_report, "n": FitResult(final_size_pt=body_pt)},
    })]})

    out = PptxWriter(styled, manifest).write(deck, tmp_path / "deck.pptx")
    written = next(
        s for s in Presentation(str(out)).slides[0].shapes
        if s.has_text_frame and s.text_frame.text == "Сноска"
    )
    assert '<a:schemeClr val="lt1"/>' in written._element.xml


def accent_title_light_body(src: Path, dst: Path) -> Path:
    """Заголовок акцентный, текст светлый — как на части макетов VK Education."""
    def style(ref: str) -> str:
        return (f"<a:lstStyle><a:lvl1pPr><a:defRPr><a:solidFill><a:schemeClr val=\"{ref}\"/>"
                "</a:solidFill></a:defRPr></a:lvl1pPr></a:lstStyle>")

    def transform(xml: str) -> str:
        xml = xml.replace("<a:lstStyle/>", style("accent1"), 1)
        return xml.replace("<a:lstStyle/>", style("lt1"), 1)

    return rewrite_part(src, dst, "ppt/slideLayouts/slideLayout2.xml", transform)


def test_free_text_takes_the_body_color_not_the_title_color(
    template: Path, tmp_path: Path
) -> None:
    styled = accent_title_light_body(template, tmp_path / "styled.pptx")
    manifest = parse(styled, tmp_path)
    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    title_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.TITLE)
    box = region(manifest, 1, 2)
    slide = SlideIR(
        slide_id="s01", layout_id=layout_of(manifest, LayoutKind.BULLETS), variant="A",
        blocks=[TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Итоги"),
                TextBlock(block_id="n", role=TextRole.BODY, text="Сноска", **box)],
        fit_report={"t": FitResult(final_size_pt=title_pt),
                    "n": FitResult(final_size_pt=body_pt)},
    )
    deck = DeckIR(deck_id="d", variant="A", template_id=manifest.template_id, seed=1,
                  slides=[slide])
    out = PptxWriter(styled, manifest).write(deck, tmp_path / "deck.pptx")
    note = next(s for s in Presentation(str(out)).slides[0].shapes
                if s.has_text_frame and s.text_frame.text == "Сноска")
    assert '<a:schemeClr val="lt1"/>' in note._element.xml


def test_fitted_table_stays_inside_its_box_as_written(template: Path, tmp_path: Path) -> None:
    """Вписывание и запись таблицы через настоящие `fit_slide` и шрифты, а не руками."""
    manifest = parse(template, tmp_path)
    fonts = theme_fonts(tmp_path, manifest)
    box = region(manifest, 1, 2)
    table = TableBlock(block_id="tb", header=["Показатель", "Значение"],
                       rows=[["очень длинное описание показателя " * 3, "1"], ["б", "2"]],
                       **box)
    slide = SlideIR(slide_id="s01", layout_id=layout_of(manifest, LayoutKind.TITLE),
                    variant="A",
                    blocks=[TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE,
                                      text="Итоги"), table])
    slide = fit_slide(slide, manifest, fonts=fonts)
    assert not slide.fit_report["tb"].overflow
    deck = DeckIR(deck_id="d", variant="A", template_id=manifest.template_id, seed=1,
                  slides=[slide])
    out = PptxWriter(template, manifest, fonts=fonts).write(deck, tmp_path / "deck.pptx")
    frame = next(s for s in Presentation(str(out)).slides[0].shapes if s.has_table)
    heights = [row.height for row in frame.table.rows]
    assert heights[1] > heights[2]
    assert sum(heights) <= box["cy"]


def test_empty_fallback_does_not_crash_the_writer(template: Path, tmp_path: Path) -> None:
    """Датасет без категорий: ни таблицы, ни буллетов не построить — ошибка валидации,
    а не исключение pydantic посреди записи."""
    manifest = parse(template, tmp_path)
    content = content_with_image(tmp_path).model_copy(update={"datasets": [Dataset(
        dataset_id="d001", title="Пусто", categories=[], series=[Series(name="а", values=[])],
    )]})
    pie = ChartBlock(block_id="c", chart_type=ChartType.PIE, dataset_ref="d001",
                     **region(manifest, 1, 2))
    writer = PptxWriter(template, manifest, fonts=theme_fonts(tmp_path, manifest))
    with pytest.raises(WriterError, match="категорий"):
        writer.write(visual_deck(manifest, pie), tmp_path / "deck.pptx", content=content)


# --- change (21): составные компоненты и иконки ------------------------------------------


def components_deck(manifest: TemplateManifest, fonts: FontLibrary) -> DeckIR:
    """Процесс, цикл и шкала времени с иконкой — вписаны настоящим `fit_slide`."""
    slides = []
    for i, pattern in enumerate(["process", "cycle", "timeline"], 1):
        box = region(manifest, 1, 2)
        side = box["cy"] // 3
        blocks: list[object] = [
            TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Как мы работаем"),
            SmartArtBlock(block_id="sa", pattern=pattern,
                          items=["Сбор данных", "Анализ", "Решение", "Контроль"], **box),
            IconBlock(block_id="ic", query="shield-check", color_ref=ColorRef.ACCENT2,
                      x=box["x"], y=box["y"] - side, cx=side, cy=side),
        ]
        slide = SlideIR(slide_id=f"s{i:02d}", layout_id=layout_of(manifest, LayoutKind.TITLE),
                        variant="A", blocks=blocks)  # type: ignore[arg-type]
        slides.append(fit_slide(slide, manifest, fonts=fonts))
    return DeckIR(deck_id="d", variant="A", template_id=manifest.template_id, seed=1,
                  slides=slides)


def test_components_and_icons_are_native_editable_shapes(template: Path, tmp_path: Path) -> None:
    manifest = parse(template, tmp_path)
    fonts = theme_fonts(tmp_path, manifest)
    deck = components_deck(manifest, fonts)
    assert not any(fit.overflow for s in deck.slides for fit in s.fit_report.values())
    writer = PptxWriter(template, manifest, fonts=fonts)
    out = writer.write(deck, tmp_path / "deck.pptx")
    assert writer.degradations == []

    for slide in Presentation(str(out)).slides:
        groups = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.GROUP]
        assert len(groups) == 1
        texts = [s.text_frame.text for s in groups[0].shapes if s.has_text_frame]
        assert [t for t in texts if t] == ["Сбор данных", "Анализ", "Решение", "Контроль"]
        icon = next(s for s in slide.shapes if s.name == "Иконка shield-check")
        assert "<a:custGeom>" in icon._element.xml
    for xml in slide_xml(out).values():
        assert "srgbClr" not in xml
        assert "<p:pic>" not in xml


def test_switching_the_template_recolors_components_and_icons(
    template: Path, tmp_path: Path
) -> None:
    twin = recolor_twin(template, tmp_path / "twin.pptx")
    manifest, twin_manifest = parse(template, tmp_path), parse(twin, tmp_path)
    fonts = theme_fonts(tmp_path, manifest)
    deck = components_deck(manifest, fonts)
    first = PptxWriter(template, manifest).write(deck, tmp_path / "a.pptx")
    twin_deck = deck.model_copy(update={"template_id": twin_manifest.template_id})
    second = PptxWriter(twin, twin_manifest).write(twin_deck, tmp_path / "b.pptx")

    node_fill = re.compile(r'prst="(?:roundRect|ellipse)">.*?<a:solidFill><a:schemeClr val="(\w+)"')

    def fills(path: Path) -> set[str]:
        return {ref for xml in slide_xml(path).values() for ref in node_fill.findall(xml)}

    # Заливка узлов — ссылка на accent1 в обоих файлах: цвет меняет тема, а не код.
    assert fills(first) == fills(second) == {"accent1"}
    # Цвет текста на заливке выбирается по контрасту с цветом этой темы — единственное,
    # что может отличаться между двойниками, и это тоже ссылка на тему.
    strip = re.compile(r'<a:schemeClr val="(?:dk1|lt1)"/>')
    assert ([strip.sub("", x) for x in slide_xml(first).values()]
            == [strip.sub("", x) for x in slide_xml(second).values()])


def master_with_two_levels(src: Path, dst: Path) -> Path:
    """Мастер, объявивший маркеры двух уровней: «•» и «–» с большим отступом."""
    second = (
        '<a:lvl2pPr marL="720000" indent="-360000"><a:buFont typeface="Arial"/>'
        '<a:buChar char="–"/></a:lvl2pPr>'
    )
    return rewrite_part(
        src, dst, "ppt/slideMasters/slideMaster1.xml",
        lambda xml: re.sub(r"(</a:lvl1pPr>)", rf"\g<1>{second}", xml, count=1),
    )


def test_nested_bullet_gets_the_marker_of_its_level(template: Path, tmp_path: Path) -> None:
    """До этого вложенный пункт получал знак и отступ первого уровня — то есть не уровень."""
    marked = master_with_two_levels(template, tmp_path / "levels.pptx")
    manifest = parse(marked, tmp_path)
    assert [item.char for item in manifest.bullet_levels][:2] == ["•", "–"]

    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    free = BulletsBlock(
        block_id="fb",
        items=[BulletItem(text="Первый довод"), BulletItem(text="Подробность", level=1)],
        **region(manifest, 1, 2),
    )
    deck = visual_deck(manifest)
    slide = deck.slides[0]
    deck = deck.model_copy(update={"slides": [slide.model_copy(update={
        "blocks": [*slide.blocks, free],
        "fit_report": {**slide.fit_report, "fb": FitResult(final_size_pt=body_pt)},
    })]})

    out = PptxWriter(marked, manifest).write(deck, tmp_path / "deck.pptx")
    box = next(
        shape for shape in Presentation(str(out)).slides[0].shapes
        if shape.has_text_frame and "Первый довод" in shape.text_frame.text
    )
    first, second_p = box.text_frame.paragraphs[0], box.text_frame.paragraphs[1]

    assert '<a:buChar char="•"/>' in first._p.xml
    assert '<a:buChar char="–"/>' in second_p._p.xml, "вложенный пункт со знаком верхнего уровня"
    assert int(second_p._pPr.get("marL")) > int(first._pPr.get("marL")), "уровни без сдвига"


def master_with_coloured_bullet(src: Path, dst: Path) -> Path:
    """Мастер, где маркер списка покрашен слотом темы.

    Стандартный шаблон python-pptx маркер объявляет (`buChar "•"` гарнитурой Arial),
    но цвет ему не задаёт. Цвет маркера есть у «Шаблона презентации 2024» из датасета —
    подменой воспроизводится именно этот случай.
    """
    return rewrite_part(
        src, dst, "ppt/slideMasters/slideMaster1.xml",
        lambda xml: re.sub(
            r"(<p:bodyStyle><a:lvl1pPr[^>]*>)",
            r'\g<1><a:buClr><a:schemeClr val="accent6"/></a:buClr>',
            xml, count=1,
        ),
    )


def test_free_bullets_get_the_marker_of_the_template(template: Path, tmp_path: Path) -> None:
    """Прогон 2ac85990b2f2: тезисы в свободном блоке читались как абзацы.

    Текстбокс не наследует ни знака, ни отступа: плейсхолдера-родителя у него нет.
    """
    marked = master_with_coloured_bullet(template, tmp_path / "marked.pptx")
    manifest = parse(marked, tmp_path)
    assert manifest.bullet is not None, "маркер мастера не доехал до манифеста"

    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    free = BulletsBlock(
        block_id="fb",
        items=[BulletItem(text="Первый довод"), BulletItem(text="Второй довод")],
        **region(manifest, 1, 2),
    )
    deck = visual_deck(manifest)
    slide = deck.slides[0]
    deck = deck.model_copy(update={"slides": [slide.model_copy(update={
        "blocks": [*slide.blocks, free],
        "fit_report": {**slide.fit_report, "fb": FitResult(final_size_pt=body_pt)},
    })]})

    out = PptxWriter(marked, manifest).write(deck, tmp_path / "deck.pptx")
    box = next(
        shape for shape in Presentation(str(out)).slides[0].shapes
        if shape.has_text_frame and "Первый довод" in shape.text_frame.text
    )
    xml = box._element.xml

    assert xml.count('<a:buChar char="•"/>') == 2, "маркер стоит не у каждого тезиса"
    assert '<a:buFont typeface="Arial"/>' in xml
    assert '<a:schemeClr val="accent6"/>' in xml, "цвет маркера — литералом вместо слота темы"
    assert 'indent="-' in xml, "без выноса маркер налезает на текст"


def test_plain_text_gets_no_marker(template: Path, tmp_path: Path) -> None:
    """Маркер — свойство списка. Абзац, ставший списком, был бы чужим решением."""
    marked = master_with_coloured_bullet(template, tmp_path / "marked2.pptx")
    manifest = parse(marked, tmp_path)
    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    note = TextBlock(block_id="n", role=TextRole.BODY, text="Сплошной абзац",
                     **region(manifest, 1, 2))
    deck = visual_deck(manifest)
    slide = deck.slides[0]
    deck = deck.model_copy(update={"slides": [slide.model_copy(update={
        "blocks": [*slide.blocks, note],
        "fit_report": {**slide.fit_report, "n": FitResult(final_size_pt=body_pt)},
    })]})

    out = PptxWriter(marked, manifest).write(deck, tmp_path / "deck.pptx")
    box = next(
        shape for shape in Presentation(str(out)).slides[0].shapes
        if shape.has_text_frame and "Сплошной абзац" in shape.text_frame.text
    )
    assert "buChar" not in box._element.xml


def test_free_text_is_centred_in_its_frame(template: Path, tmp_path: Path) -> None:
    """Прогон 2ac85990b2f2, s04: два тезиса сверху и восемь сантиметров пустоты под ними.

    Рамку свободному блоку считает решатель — её верхний край не решение дизайнера
    о том, где начинается текст.
    """
    manifest = parse(template, tmp_path)
    body_pt = next(s.size_pt for s in manifest.typography_scale if s.role is TextRole.BODY)
    note = TextBlock(block_id="n", role=TextRole.BODY, text="Короткая мысль",
                     **region(manifest, 1, 2))
    deck = visual_deck(manifest)
    slide = deck.slides[0]
    deck = deck.model_copy(update={"slides": [slide.model_copy(update={
        "blocks": [*slide.blocks, note],
        "fit_report": {**slide.fit_report, "n": FitResult(final_size_pt=body_pt)},
    })]})

    out = PptxWriter(template, manifest).write(deck, tmp_path / "deck.pptx")
    shapes = list(Presentation(str(out)).slides[0].shapes)
    free = next(s for s in shapes if s.has_text_frame and "Короткая мысль" in s.text_frame.text)
    in_placeholder = next(
        s for s in shapes if s.has_text_frame and s.text_frame.text and s is not free
        and s.shape_type != MSO_SHAPE_TYPE.TEXT_BOX
    )

    assert 'anchor="ctr"' in free._element.xml, "свободный текст прижат к краю рамки"
    assert 'anchor="ctr"' not in in_placeholder._element.xml, "выравнивание задал шаблон"


def test_kpi_columns_are_centred_in_their_frame(template: Path, tmp_path: Path) -> None:
    """Прогон f0eb600a3ad7: показатели полосой в верхней трети, под ними пустое поле."""
    manifest = parse(template, tmp_path)
    deck = visual_deck(
        manifest,
        KpiBlock(block_id="k", items=[KpiItem(value="37 %", label="рост")],
                 **region(manifest, 1, 2)),
    )
    out = PptxWriter(template, manifest).write(deck, tmp_path / "deck.pptx")
    column = next(
        s for s in Presentation(str(out)).slides[0].shapes
        if s.has_text_frame and "37 %" in s.text_frame.text
    )

    assert 'anchor="ctr"' in column._element.xml, "колонка показателя прижата к краю рамки"
