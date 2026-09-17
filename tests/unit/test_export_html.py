"""Экспорт .html из IR. Change (22) `export-html`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import Image

from deckforge.domain.content import Asset, Brief, ContentPackage, Dataset, Series
from deckforge.domain.enums import ChartType, ColorRef, ImageSource, TextRole
from deckforge.domain.slide import (
    BulletItem,
    BulletsBlock,
    ChartBlock,
    DeckIR,
    FitResult,
    ImageBlock,
    KpiBlock,
    KpiItem,
    SlideIR,
    TableBlock,
    TextBlock,
)
from deckforge.domain.template import TemplateManifest, ThemeColors
from deckforge.domain.units import EMU_PER_PT
from deckforge.export.html import export_html
from deckforge.rendering.writer import WriterError


def content(tmp_path: Path, *series: Series) -> ContentPackage:
    image = tmp_path / "photo.png"
    Image.new("RGB", (40, 20), "gray").save(image)
    return ContentPackage(
        brief=Brief(purpose="report", audience="команда", target_slides=3),
        assets=[Asset(asset_id="a001", kind="image", path=str(image))],
        datasets=[
            Dataset(
                dataset_id="d001",
                title="Выручка",
                categories=["2024", "2025"],
                series=list(series)
                or [
                    Series(name="Россия", values=[1.0, 2.0]),
                    Series(name="СНГ", values=[0.5, 0.7]),
                ],
                unit="млн ₽",
            )
        ],
    )


def half(manifest: TemplateManifest, part: int) -> dict[str, int]:
    box = manifest.content_bbox
    return {"x": box.x, "y": box.y + part * box.cy // 2, "cx": box.cx, "cy": box.cy // 2}


def deck(manifest: TemplateManifest, *extra: object) -> DeckIR:
    title_pt = manifest.typography(TextRole.TITLE).size_pt  # type: ignore[union-attr]
    body_pt = manifest.typography(TextRole.BODY).size_pt  # type: ignore[union-attr]
    first = SlideIR(
        slide_id="s01",
        layout_id="L07",
        variant="A",
        blocks=[
            TextBlock(
                block_id="t",
                placeholder_idx=0,
                role=TextRole.TITLE,
                text="Выручка <script>alert(1)</script> & рост",
            ),
            BulletsBlock(
                block_id="b",
                placeholder_idx=1,
                items=[BulletItem(text="Довод"), BulletItem(text="Деталь", level=1)],
            ),
        ],
        speaker_note="Начать с вывода",
        fit_report={"t": FitResult(final_size_pt=title_pt), "b": FitResult(final_size_pt=body_pt)},
    )
    slides = [first]
    if extra:
        report = {"t": FitResult(final_size_pt=title_pt)}
        for block in extra:
            if isinstance(block, TableBlock | KpiBlock):
                report[block.block_id] = FitResult(final_size_pt=body_pt)
        slides.append(
            SlideIR(
                slide_id="s02",
                layout_id="L07",
                variant="A",
                blocks=[
                    TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Цифры"),
                    *extra,
                ],  # type: ignore[list-item]
                fit_report=report,
            )
        )
    return DeckIR(deck_id="d", variant="A", template_id=manifest.template_id, seed=1, slides=slides)


def html_of(
    manifest: TemplateManifest, tmp_path: Path, *extra: object, data: ContentPackage | None = None
) -> str:
    out = export_html(
        deck(manifest, *extra), manifest, tmp_path / "deck.html", content=data or content(tmp_path)
    )
    return out.read_text(encoding="utf-8")


def test_file_is_self_contained(manifest: TemplateManifest, tmp_path: Path) -> None:
    html = html_of(
        manifest,
        tmp_path,
        ImageBlock(block_id="i", source=ImageSource.ASSET, asset_ref="a001", **half(manifest, 1)),
    )
    assert not re.search(r'(src|href)="https?:|url\(\s*["\']?https?:|@import', html)
    assert 'src="data:image/png;base64,' in html


def test_theme_colors_become_css_variables(manifest: TemplateManifest, tmp_path: Path) -> None:
    html = html_of(manifest, tmp_path)
    root = html.split(":root", 1)[1].split("}", 1)[0]
    for ref in ColorRef:
        assert f"--{ref.value}: {manifest.theme.colors.get(ref)};" in root
    body = html.split("</style>", 1)[1]
    assert not re.search(r"#[0-9A-Fa-f]{6}\b", body), "в разметке цвета только ссылками"


def test_text_is_escaped(manifest: TemplateManifest, tmp_path: Path) -> None:
    html = html_of(manifest, tmp_path)
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; рост" in html


def test_blocks_are_placed_and_sized_from_manifest_and_fit(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    html = html_of(manifest, tmp_path)
    layout = manifest.layout("L07")
    assert layout is not None
    ph = layout.placeholder(0)
    assert ph is not None
    cx, cy = manifest.slide_size.cx_emu, manifest.slide_size.cy_emu
    title = re.search(r'<div class="block text" data-block="t" style="([^"]+)"', html)
    assert title is not None
    style = title.group(1)
    assert f"left: {ph.x / cx * 100:.4f}%" in style
    assert f"top: {ph.y / cy * 100:.4f}%" in style
    title_pt = manifest.typography(TextRole.TITLE).size_pt  # type: ignore[union-attr]
    assert f"font-size: {title_pt * EMU_PER_PT / cx * 100:.4f}cqw" in style
    assert "color: var(--dk1)" in style


def test_bullet_levels_and_notes(manifest: TemplateManifest, tmp_path: Path) -> None:
    html = html_of(manifest, tmp_path)
    assert '<li class="level-0">Довод</li>' in html
    assert '<li class="level-1">Деталь</li>' in html
    assert '<aside class="notes" hidden>Начать с вывода</aside>' in html


def test_chart_is_an_svg_in_theme_colors(manifest: TemplateManifest, tmp_path: Path) -> None:
    chart = ChartBlock(
        block_id="c", chart_type=ChartType.CLUSTERED_COLUMN, dataset_ref="d001", **half(manifest, 1)
    )
    html = html_of(manifest, tmp_path, chart)
    svg = html.split('data-block="c"', 1)[1].split("</svg>", 1)[0]
    assert "<svg" in svg
    assert "var(--accent1)" in svg and "var(--accent2)" in svg
    assert svg.count('class="bar"') == 4
    assert "млн ₽" in svg


@pytest.mark.parametrize("chart_type", [ChartType.PIE, ChartType.DOUGHNUT])
def test_round_charts_have_a_slice_per_category(
    manifest: TemplateManifest, tmp_path: Path, chart_type: ChartType
) -> None:
    chart = ChartBlock(block_id="c", chart_type=chart_type, dataset_ref="d001", **half(manifest, 1))
    data = content(tmp_path, Series(name="Доля", values=[60.0, 40.0]))
    html = html_of(manifest, tmp_path, chart, data=data)
    assert html.count('class="slice"') == 2


@pytest.mark.parametrize(
    "chart_type",
    [ChartType.STACKED_BAR, ChartType.LINE_MARKERS, ChartType.AREA, ChartType.SCATTER],
)
def test_every_chart_type_renders(
    manifest: TemplateManifest, tmp_path: Path, chart_type: ChartType
) -> None:
    chart = ChartBlock(block_id="c", chart_type=chart_type, dataset_ref="d001", **half(manifest, 1))
    html = html_of(manifest, tmp_path, chart)
    assert "<svg" in html.split('data-block="c"', 1)[1]


def test_impossible_chart_degrades_like_in_pptx(manifest: TemplateManifest, tmp_path: Path) -> None:
    pie = ChartBlock(
        block_id="c", chart_type=ChartType.PIE, dataset_ref="d001", **half(manifest, 1)
    )
    html = html_of(manifest, tmp_path, pie)
    block = html.split('data-block="c"', 1)[1].split("</div>", 1)[0]
    assert "<table" in block
    assert "<svg" not in block


def test_table_and_kpi(manifest: TemplateManifest, tmp_path: Path) -> None:
    table = TableBlock(
        block_id="tb", header=["Год", "Выручка"], rows=[["2025", "2"]], **half(manifest, 1)
    )
    kpi = KpiBlock(
        block_id="k",
        items=[KpiItem(value="37 %", label="рост", color_ref=ColorRef.ACCENT3)],
        **{**half(manifest, 0), "cy": half(manifest, 0)["cy"] // 2},
    )
    html = html_of(manifest, tmp_path, table, kpi)
    assert "<th>Год</th><th>Выручка</th>" in html
    assert "<td>2025</td><td>2</td>" in html
    assert '<div class="kpi-value" style="color: var(--accent3)">37 %</div>' in html


def test_invalid_deck_writes_no_file(manifest: TemplateManifest, tmp_path: Path) -> None:
    broken = deck(manifest).model_copy(update={"template_id": "sha256:" + "f" * 64})
    out = tmp_path / "deck.html"
    with pytest.raises(WriterError):
        export_html(broken, manifest, out)
    assert not out.exists()


def test_switching_the_template_changes_only_the_palette(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    chart = ChartBlock(
        block_id="c", chart_type=ChartType.CLUSTERED_COLUMN, dataset_ref="d001", **half(manifest, 1)
    )
    colors = manifest.theme.colors.model_dump()
    twin = manifest.model_copy(
        update={
            "theme": manifest.theme.model_copy(
                update={"colors": ThemeColors(**{**colors, "accent1": "#C2185B"})}
            )
        }
    )
    first = html_of(manifest, tmp_path, chart)
    second = html_of(twin, tmp_path, chart)
    strip = re.compile(r":root\s*\{[^}]*\}")
    assert strip.sub("", first) == strip.sub("", second)
    assert "--accent1: #C2185B;" in second


def test_series_colors_invisible_on_the_slide_background_are_skipped(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    """Фон html-слайда — `lt1`: цвет серии, почти неразличимый на нём, пропускается.
    У VK Tech `accent2` белый: в pptx его спасает тёмный фон макета, в html фона макета нет."""
    colors = manifest.theme.colors.model_dump()
    white_accent = manifest.model_copy(
        update={
            "theme": manifest.theme.model_copy(
                update={"colors": ThemeColors(**{**colors, "accent2": colors["lt1"]})}
            )
        }
    )
    chart = ChartBlock(
        block_id="c", chart_type=ChartType.CLUSTERED_COLUMN, dataset_ref="d001", **half(manifest, 1)
    )
    svg = html_of(white_accent, tmp_path, chart).split('data-block="c"', 1)[1].split("</svg>")[0]
    assert "var(--accent2)" not in svg
    assert "var(--accent1)" in svg and "var(--accent3)" in svg


def test_kpi_items_share_the_width(manifest: TemplateManifest, tmp_path: Path) -> None:
    kpi = KpiBlock(
        block_id="k",
        items=[KpiItem(value="1", label="а"), KpiItem(value="2", label="б")],
        **half(manifest, 1),
    )
    html = html_of(manifest, tmp_path, kpi)
    assert '<div class="kpi-row"' in html
    assert re.search(r"\.kpi-row > div \{[^}]*flex: 1", html)


def test_table_keeps_its_own_height(manifest: TemplateManifest, tmp_path: Path) -> None:
    """Как в pptx: строки не растягиваются на всю рамку."""
    html = html_of(manifest, tmp_path)
    rule = re.search(r"\.block table \{([^}]*)\}", html)
    assert rule is not None
    assert "height" not in rule.group(1)
