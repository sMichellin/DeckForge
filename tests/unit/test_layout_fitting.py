"""Вписывание текста: как есть → ступень кегля → сокращение → деление. Change (12)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.base import BBox
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import BulletItem, BulletsBlock, ChartBlock, SlideIR, TextBlock
from deckforge.domain.template import PlaceholderSpec, TemplateManifest
from deckforge.domain.units import EMU_PER_CM
from deckforge.layout.fitting import LayoutFitError, fit_block, fit_slide, fit_text
from deckforge.layout.fonts import FontLibrary
from tests.unit.test_layout_fonts import make_font

NARROW_IDX = 5


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    """Гарнитуры темы синтетического манифеста, знак шириной в половину кегля."""
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=500, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=500)
    return FontLibrary([tmp_path])


@pytest.fixture
def narrow(manifest: TemplateManifest) -> TemplateManifest:
    """Макет с узким плейсхолдером 4 × 3 см рядом с обычным телом."""
    base = manifest.layout("L07")
    assert base is not None
    placeholder = PlaceholderSpec(
        idx=NARROW_IDX, ph_type="BODY", role=TextRole.BODY,
        x=manifest.grid.margins_emu.left, y=5 * EMU_PER_CM, cx=4 * EMU_PER_CM, cy=3 * EMU_PER_CM,
    )
    layout = base.model_copy(
        update={"layout_id": "L_NARROW", "placeholders": [*base.placeholders, placeholder]}
    )
    return manifest.model_copy(update={"layouts": [*manifest.layouts, layout]})


def body_box(manifest: TemplateManifest) -> BBox:
    layout = manifest.layout("L07")
    assert layout is not None
    ph = layout.placeholder(1)
    assert ph is not None
    return ph.bbox


def fit_body(text: str, manifest: TemplateManifest, fonts: FontLibrary, box: BBox) -> object:
    return fit_text(
        text, box=box, manifest=manifest, start_size_pt=18,
        font_family=manifest.theme.fonts.minor_latin, fonts=fonts,
    )


# --- fit_text ----------------------------------------------------------------


def test_short_text_fits_as_is(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    result = fit_text(
        "Выручка выросла на 37 %", box=body_box(manifest), manifest=manifest,
        start_size_pt=18, font_family=manifest.theme.fonts.minor_latin, fonts=fonts,
    )
    assert result.overflow is False
    assert result.final_size_pt == 18
    assert result.strategy == "as_is"
    assert result.lines == 1


def test_overflow_steps_down_the_template_ladder(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """60 знаков в рамке 10 × 1,4 см: при 18 pt — 2 строки и не влезают, при 12 pt — влезают."""
    box = BBox(x=0, y=0, cx=10 * EMU_PER_CM, cy=int(1.4 * EMU_PER_CM))
    result = fit_text(
        "слово " * 10, box=box, manifest=manifest, start_size_pt=18,
        font_family=manifest.theme.fonts.minor_latin, fonts=fonts,
    )
    assert result.overflow is False
    assert result.strategy == "shrink"
    assert result.final_size_pt in manifest.size_ladder_pt
    assert result.final_size_pt < 18


def test_size_never_leaves_the_template_scale(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    box = BBox(x=0, y=0, cx=3 * EMU_PER_CM, cy=EMU_PER_CM)
    result = fit_text(
        "очень длинный текст " * 30, box=box, manifest=manifest, start_size_pt=18,
        font_family=manifest.theme.fonts.minor_latin, fonts=fonts,
    )
    assert result.overflow is True
    assert result.final_size_pt == min(manifest.size_ladder_pt)


def test_without_shrink_the_size_stays(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    box = BBox(x=0, y=0, cx=3 * EMU_PER_CM, cy=EMU_PER_CM)
    result = fit_text(
        "очень длинный текст " * 30, box=box, manifest=manifest, start_size_pt=18,
        font_family=manifest.theme.fonts.minor_latin, fonts=fonts, allow_shrink=False,
    )
    assert result.overflow is True
    assert result.final_size_pt == 18


def test_single_paragraph_overflow_is_shortened_not_split(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    box = BBox(x=0, y=0, cx=3 * EMU_PER_CM, cy=EMU_PER_CM)
    result = fit_text(
        "а " * 400, box=box, manifest=manifest, start_size_pt=18,
        font_family=manifest.theme.fonts.minor_latin, fonts=fonts,
    )
    assert result.strategy == "shorten"


def test_many_paragraphs_far_over_the_box_are_split(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    box = BBox(x=0, y=0, cx=10 * EMU_PER_CM, cy=2 * EMU_PER_CM)
    result = fit_text(
        "\n".join(f"пункт номер {i}" for i in range(30)), box=box, manifest=manifest,
        start_size_pt=18, font_family=manifest.theme.fonts.minor_latin, fonts=fonts,
    )
    assert result.overflow is True
    assert result.strategy == "split"


def test_slight_overflow_of_many_paragraphs_is_shortened(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Лишняя строка — повод сократить, а не делить слайд на два полупустых."""
    ladder_min = min(manifest.size_ladder_pt)
    line_cm = 1.2 * ladder_min * 12_700 / EMU_PER_CM
    box = BBox(x=0, y=0, cx=20 * EMU_PER_CM, cy=int((4 * line_cm + 0.254) * EMU_PER_CM))
    result = fit_text(
        "\n".join(["пункт"] * 5), box=box, manifest=manifest, start_size_pt=18,
        font_family=manifest.theme.fonts.minor_latin, fonts=fonts,
    )
    assert result.overflow is True
    assert result.strategy == "shorten"


def test_required_height_reported_at_final_size(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    result = fit_text(
        "а\nб", box=body_box(manifest), manifest=manifest, start_size_pt=18,
        font_family=manifest.theme.fonts.minor_latin, fonts=fonts,
    )
    assert result.lines == 2
    assert result.required_cy_emu == round(2 * 1.2 * 18 * 12_700)


# --- fit_block / fit_slide ----------------------------------------------------


def slide(*blocks: object, layout_id: str = "L07") -> SlideIR:
    return SlideIR(slide_id="s01", layout_id=layout_id, variant="A", blocks=list(blocks))


def test_exit_criterion_500_chars_in_narrow_placeholder_overflow_before_writing(
    narrow: TemplateManifest, fonts: FontLibrary
) -> None:
    """Критерий выхода change (12): переполнение видно в `fit_report` до создания файла."""
    text = ("Выручка компании выросла за год благодаря новым клиентам. " * 10)[:500]
    assert len(text) == 500
    result = fit_slide(
        slide(
            TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Итоги года"),
            TextBlock(block_id="b", placeholder_idx=NARROW_IDX, role=TextRole.BODY, text=text),
            layout_id="L_NARROW",
        ),
        narrow,
        fonts=fonts,
    )
    assert result.fit_report["b"].overflow is True
    assert result.fit_report["b"].strategy in {"shorten", "split"}
    assert result.fit_report["t"].overflow is False


def test_title_is_never_shrunk(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    title_step = manifest.typography(TextRole.TITLE)
    assert title_step is not None
    block = TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Заголовок " * 40)
    layout = manifest.layout("L07")
    assert layout is not None
    result = fit_block(block, layout, manifest, fonts=fonts)
    assert result.overflow is True
    assert result.final_size_pt == title_step.size_pt
    assert result.strategy == "shorten"


def test_bullets_are_measured_as_paragraphs(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    layout = manifest.layout("L07")
    assert layout is not None
    block = BulletsBlock(
        block_id="b", placeholder_idx=1, items=[BulletItem(text=t) for t in ("а", "б", "в")]
    )
    result = fit_block(block, layout, manifest, fonts=fonts)
    assert result.lines == 3
    assert result.overflow is False


def test_explicit_size_is_the_starting_point(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    layout = manifest.layout("L07")
    assert layout is not None
    block = TextBlock(block_id="b", placeholder_idx=1, role=TextRole.BODY, text="а", size_pt=12)
    assert fit_block(block, layout, manifest, fonts=fonts).final_size_pt == 12


def test_size_outside_the_ladder_snaps_down_to_it(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """13 pt в шкале 40/24/18/12 нет: берётся ступень ниже, своих кеглей не бывает."""
    layout = manifest.layout("L07")
    assert layout is not None
    block = TextBlock(block_id="b", placeholder_idx=1, role=TextRole.BODY, text="а", size_pt=13)
    result = fit_block(block, layout, manifest, fonts=fonts)
    assert result.final_size_pt == 12
    assert result.final_size_pt in manifest.size_ladder_pt


def test_explicit_coordinates_win_over_placeholder(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    layout = manifest.layout("L07")
    assert layout is not None
    tiny = TextBlock(
        block_id="b", placeholder_idx=1, role=TextRole.BODY, text="слово " * 50,
        x=0, y=0, cx=2 * EMU_PER_CM, cy=EMU_PER_CM,
    )
    assert fit_block(tiny, layout, manifest, fonts=fonts).overflow is True


def test_missing_placeholder_is_an_error(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    layout = manifest.layout("L07")
    assert layout is not None
    block = TextBlock(block_id="b", placeholder_idx=99, role=TextRole.BODY, text="а")
    with pytest.raises(LayoutFitError):
        fit_block(block, layout, manifest, fonts=fonts)


def test_unknown_layout_is_an_error(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    with pytest.raises(LayoutFitError):
        fit_slide(slide(layout_id="нет такого"), manifest, fonts=fonts)


def test_fit_slide_reports_only_text_blocks(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    result = fit_slide(
        slide(
            TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Итоги"),
            ChartBlock(block_id="c", chart_type="clustered_bar", dataset_ref="d1"),
        ),
        manifest,
        fonts=fonts,
    )
    assert set(result.fit_report) == {"t"}
    assert result.blocks == slide(
        TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Итоги"),
        ChartBlock(block_id="c", chart_type="clustered_bar", dataset_ref="d1"),
    ).blocks


def test_fit_slide_measures_with_theme_fonts_of_the_role(
    tmp_path: Path, manifest: TemplateManifest
) -> None:
    """Гарнитура берётся из типошкалы роли: у заголовка своя, у тела своя."""
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=900, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=100)
    fonts = FontLibrary([tmp_path])
    text = "слово " * 40
    result = fit_slide(
        slide(
            TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text=text),
            TextBlock(block_id="b", placeholder_idx=1, role=TextRole.BODY, text=text),
        ),
        manifest,
        fonts=fonts,
    )
    assert result.fit_report["t"].overflow is True
    assert result.fit_report["b"].overflow is False


# --- заголовок и рамка, которая не держит кегль роли --------------------------


def test_title_shrinks_when_the_band_cannot_hold_one_line(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Ограничивает рамка, а не текст: сокращать нечего, и шаг вниз по шкале законен.

    Прогон 80e7af41ab54: 7 заголовков из 12 обрывались многоточием, потому что полоса
    заголовка ниже одной строки кеглем роли, а уменьшать его было запрещено.
    """
    title_ph = PlaceholderSpec(
        idx=9, ph_type="TITLE", role=TextRole.TITLE,
        x=manifest.grid.margins_emu.left, y=EMU_PER_CM, cx=20 * EMU_PER_CM, cy=EMU_PER_CM,
    )
    base = manifest.layout("L07")
    assert base is not None
    flat = manifest.model_copy(
        update={
            "layouts": [
                *manifest.layouts,
                base.model_copy(
                    update={"layout_id": "L_BAND", "placeholders": [*base.placeholders, title_ph]}
                ),
            ]
        }
    )
    block = TextBlock(block_id="t", placeholder_idx=9, role=TextRole.TITLE, text="Итоги года")
    result = fit_slide(slide(block, layout_id="L_BAND"), flat, fonts=fonts).fit_report["t"]

    assert result.final_size_pt < manifest.typography(TextRole.TITLE).size_pt
    assert result.overflow is False


def test_title_in_a_roomy_band_is_still_not_shrunk(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Правило иерархии в силе: если рамка держит кегль роли, заголовок не уменьшается."""
    long_title = "Итоги года и планы на следующий период работы компании " * 2
    block = TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text=long_title)
    result = fit_slide(slide(block), manifest, fonts=fonts).fit_report["t"]

    assert result.final_size_pt == manifest.typography(TextRole.TITLE).size_pt


# --- свободный блок растёт под свою рамку ------------------------------------


def free_block(text: str, manifest: TemplateManifest, *, role: TextRole = TextRole.BODY,
               size_pt: float | None = None) -> TextBlock:
    """Свободный блок во всю область контента: столько места отдаёт решатель, когда
    в макете нет плейсхолдера под тело (у VK WorkSpace таких макетов нет вовсе)."""
    box = manifest.content_bbox
    return TextBlock(
        block_id="free", role=role, text=text, size_pt=size_pt,
        x=box.x, y=box.y, cx=box.cx, cy=box.cy,
    )


def test_free_block_with_little_text_grows_up_the_ladder(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Прогон 693d464d54fb: четыре строки кеглем тела в рамке на всю область контента.

    Переполнения нет, и порядок деградации молчит — а слайд выглядит пустым.
    """
    layout = manifest.layout("L07")
    assert layout is not None
    body_step = manifest.typography(TextRole.BODY)
    assert body_step is not None

    grown = fit_block(free_block("Короткая мысль на слайде", manifest), layout, manifest,
                      fonts=fonts)

    assert grown.final_size_pt > body_step.size_pt, "блок остался жаться к верхнему краю"
    assert grown.final_size_pt in manifest.size_ladder_pt, "кегль вне шкалы шаблона"
    assert grown.strategy == "grow"
    assert grown.overflow is False


def test_growth_stops_below_the_title_size_of_this_template(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Тело вровень с заголовком стирает иерархию не хуже, чем тело крупнее него."""
    from deckforge.domain.rules import next_size_down

    layout = manifest.layout("L07")
    assert layout is not None
    title_step = manifest.typography(TextRole.TITLE)
    assert title_step is not None
    cap = next_size_down(manifest, title_step.size_pt) or title_step.size_pt

    grown = fit_block(free_block("Два слова", manifest), layout, manifest, fonts=fonts)

    assert grown.final_size_pt <= cap


def test_block_that_fills_its_frame_is_left_alone(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Расти некуда: текст и так занимает рамку. Лишняя ступень — переполнение."""
    layout = manifest.layout("L07")
    assert layout is not None
    long_text = "Плотный абзац про выручку и корпоративных клиентов. " * 40

    fitted = fit_block(free_block(long_text, manifest), layout, manifest, fonts=fonts)

    assert fitted.strategy != "grow"


def test_placeholder_and_title_never_grow(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Плейсхолдер — решение автора шаблона; заголовок задаёт иерархию слайда."""
    layout = manifest.layout("L07")
    assert layout is not None
    body_step = manifest.typography(TextRole.BODY)
    assert body_step is not None

    in_placeholder = TextBlock(
        block_id="b", placeholder_idx=1, role=TextRole.BODY, text="Короткая мысль"
    )
    assert fit_block(in_placeholder, layout, manifest, fonts=fonts).strategy != "grow"

    title = free_block("Короткий вывод", manifest, role=TextRole.TITLE)
    assert fit_block(title, layout, manifest, fonts=fonts).strategy != "grow"

    fixed = free_block("Короткая мысль", manifest, size_pt=body_step.size_pt)
    assert fit_block(fixed, layout, manifest, fonts=fonts).strategy != "grow"
