"""Таблицы и KPI вписываются так же, как текст. Change (14) `native-charts-tables`."""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.base import BBox
from deckforge.domain.content import Brief, ContentPackage, Dataset, Series
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import KpiBlock, KpiItem, SlideIR, TableBlock
from deckforge.domain.template import TemplateManifest
from deckforge.domain.units import EMU_PER_CM
from deckforge.layout.fitting import (
    LayoutFitError,
    fit_kpi,
    fit_slide,
    fit_table,
    table_row_heights,
)
from deckforge.layout.fonts import FontLibrary
from deckforge.layout.tabular import (
    dataset_bullets,
    format_number,
    table_cells,
    table_has_header,
)
from tests.unit.test_layout_fonts import make_font


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=500, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=500)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=550, bold=True)
    return FontLibrary([tmp_path])


def dataset(**update: object) -> Dataset:
    base = Dataset(
        dataset_id="d001",
        title="Выручка",
        categories=["2024", "2025"],
        series=[Series(name="Россия", values=[1.5, 2.0]), Series(name="СНГ", values=[0.5, None])],
        unit="млн ₽",
    )
    return base.model_copy(update=update)


# --- ячейки --------------------------------------------------------------------


def test_cells_come_from_the_block_when_given() -> None:
    block = TableBlock(block_id="t", header=["Год", "Выручка"], rows=[["2025", "2,0"]])
    assert table_cells(block, None) == [["Год", "Выручка"], ["2025", "2,0"]]


def test_cells_are_built_from_the_dataset() -> None:
    block = TableBlock(block_id="t", dataset_ref="d001")
    assert table_cells(block, dataset()) == [
        ["", "Россия", "СНГ"],
        ["2024", "1,5", "0,5"],
        ["2025", "2", "—"],
    ]


def test_dataset_table_without_dataset_is_an_error() -> None:
    with pytest.raises(LayoutFitError):
        table_cells(TableBlock(block_id="t", dataset_ref="d001"), None)


def test_dataset_bullets_keep_category_series_and_unit() -> None:
    assert dataset_bullets(dataset()) == [
        "2024: Россия — 1,5, СНГ — 0,5 млн ₽",
        "2025: Россия — 2, СНГ — — млн ₽",
    ]


def test_single_series_bullets_are_short() -> None:
    single = dataset(series=[Series(name="Россия", values=[1.5, 2.0])])
    assert dataset_bullets(single) == ["2024: 1,5 млн ₽", "2025: 2 млн ₽"]


# --- fit_table -----------------------------------------------------------------


def test_small_table_fits_at_body_size(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    body = manifest.typography(TextRole.BODY)
    assert body is not None
    block = TableBlock(block_id="t", header=["Год", "Выручка"], rows=[["2025", "2,0"]])
    box = BBox(x=0, y=0, cx=20 * EMU_PER_CM, cy=5 * EMU_PER_CM)
    result = fit_table(block, box, manifest, fonts=fonts)
    assert result.overflow is False
    assert result.final_size_pt == body.size_pt
    assert result.lines == 2


def test_tall_table_steps_down_the_ladder(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    rows = [[f"строка {i}", "значение"] for i in range(6)]
    block = TableBlock(block_id="t", header=["Показатель", "Значение"], rows=rows)
    box = BBox(x=0, y=0, cx=20 * EMU_PER_CM, cy=int(5.5 * EMU_PER_CM))
    result = fit_table(block, box, manifest, fonts=fonts)
    assert result.overflow is False
    assert result.strategy == "shrink"
    assert result.final_size_pt in manifest.size_ladder_pt


def test_wrapping_cells_make_rows_taller(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    """Длинный текст в узкой колонке переносится — высота считается по строкам ячейки."""
    short = TableBlock(block_id="t", header=["а", "б"], rows=[["в", "г"]])
    long = TableBlock(block_id="t", header=["а", "б"], rows=[["слово " * 12, "г"]])
    box = BBox(x=0, y=0, cx=8 * EMU_PER_CM, cy=20 * EMU_PER_CM)
    assert (fit_table(long, box, manifest, fonts=fonts).required_cy_emu or 0) > (
        fit_table(short, box, manifest, fonts=fonts).required_cy_emu or 0
    )


def test_table_that_never_fits_overflows(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    rows = [[f"строка {i}", "значение"] for i in range(40)]
    block = TableBlock(block_id="t", header=["Показатель", "Значение"], rows=rows)
    box = BBox(x=0, y=0, cx=10 * EMU_PER_CM, cy=2 * EMU_PER_CM)
    result = fit_table(block, box, manifest, fonts=fonts)
    assert result.overflow is True
    assert result.final_size_pt == min(manifest.size_ladder_pt)


# --- fit_kpi -------------------------------------------------------------------


def kpi(*values: str) -> KpiBlock:
    return KpiBlock(block_id="k", items=[KpiItem(value=v, label="рост за год") for v in values],
                    x=0, y=0, cx=24 * EMU_PER_CM, cy=4 * EMU_PER_CM)


def test_kpi_fits_at_subtitle_size(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    subtitle = manifest.typography(TextRole.SUBTITLE)
    assert subtitle is not None
    block = kpi("37 %", "×2,3", "1 200")
    assert block.bbox is not None
    result = fit_kpi(block, block.bbox, manifest, fonts=fonts)
    assert result.overflow is False
    assert result.final_size_pt == subtitle.size_pt


def test_long_kpi_value_shrinks_to_stay_on_one_line(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    block = kpi("1 200 000 000 ₽", "37 %", "12", "x2", "5", "7")
    assert block.bbox is not None
    subtitle = manifest.typography(TextRole.SUBTITLE)
    assert subtitle is not None
    result = fit_kpi(block, block.bbox, manifest, fonts=fonts)
    assert result.final_size_pt < subtitle.size_pt
    assert result.overflow is False


def test_kpi_too_narrow_overflows(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    block = KpiBlock(block_id="k", items=[KpiItem(value="1 200 000 000 000", label="а")],
                     x=0, y=0, cx=EMU_PER_CM, cy=EMU_PER_CM)
    assert block.bbox is not None
    assert fit_kpi(block, block.bbox, manifest, fonts=fonts).overflow is True


# --- fit_slide -----------------------------------------------------------------


def test_fit_slide_reports_tables_and_kpi(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    content = ContentPackage(
        brief=Brief(purpose="report", audience="команда", target_slides=1),
        datasets=[dataset()],
    )
    box = manifest.content_bbox
    slide = SlideIR(
        slide_id="s", layout_id="L07", variant="A",
        blocks=[
            TableBlock(block_id="t", dataset_ref="d001",
                       x=box.x, y=box.y, cx=box.cx, cy=box.cy // 2),
            kpi("37 %"),
        ],
    )
    report = fit_slide(slide, manifest, fonts=fonts, content=content).fit_report
    assert set(report) == {"t", "k"}


def test_block_without_coordinates_cannot_be_fitted(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    slide = SlideIR(slide_id="s", layout_id="L07", variant="A",
                    blocks=[TableBlock(block_id="t", header=["а"], rows=[["б"]])])
    with pytest.raises(LayoutFitError):
        fit_slide(slide, manifest, fonts=fonts)


def test_empty_table_row_is_a_layout_error() -> None:
    with pytest.raises(LayoutFitError, match="пуст"):
        table_cells(TableBlock(block_id="t", header=["а", "б"], rows=[[]]), None)


def test_header_without_rows_is_a_layout_error() -> None:
    with pytest.raises(LayoutFitError, match="строк"):
        table_cells(TableBlock(block_id="t", header=["а"]), None)


def test_dataset_without_categories_is_a_layout_error() -> None:
    with pytest.raises(LayoutFitError, match="строк"):
        table_cells(TableBlock(block_id="t", dataset_ref="d001"), dataset(categories=[]))


def test_tiny_numbers_are_not_rounded_to_zero() -> None:
    assert format_number(1e-13) == "0,0000000000001"


def test_row_heights_sum_to_the_reported_height(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Писатель ставит строкам ровно эти высоты: иначе python-pptx поделит рамку поровну,
    и высокая строка вылезет за рамку, хотя расчёт говорил «влезает»."""
    block = TableBlock(block_id="t", header=["а", "б"],
                       rows=[["слово " * 12, "г"], ["в", "г"], ["в", "г"]])
    box = BBox(x=0, y=0, cx=8 * EMU_PER_CM, cy=20 * EMU_PER_CM)
    result = fit_table(block, box, manifest, fonts=fonts)
    heights = table_row_heights(block, box, manifest, result.final_size_pt, fonts=fonts)
    assert len(heights) == 4
    assert sum(heights) == result.required_cy_emu
    assert heights[1] > heights[2] == heights[3]


def test_first_row_is_bold_only_when_there_is_a_header(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    assert table_has_header(TableBlock(block_id="t", header=["а"], rows=[["б"]]))
    assert table_has_header(TableBlock(block_id="t", dataset_ref="d001"))
    assert not table_has_header(TableBlock(block_id="t", rows=[["а"], ["б"]]))
