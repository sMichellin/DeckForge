"""Узел `fit`: сокращение до записи и плейсхолдер вместо координат модели. Change (17).

Прогон 19.09 на VK WorkSpace падал на стадии `render`: вписывание назначало `shorten`,
а сокращать до записи было некому — фикс `shorten_text` живёт в аудите, после записи.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import BulletItem, BulletsBlock, SlideIR, TextBlock
from deckforge.domain.template import PlaceholderSpec, TemplateManifest
from deckforge.domain.units import EMU_PER_CM
from deckforge.layout.fitting import fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.nodes.fit import _fit_shortening, _into_placeholders
from tests.unit.test_layout_fonts import make_font

NARROW_IDX = 5

CONTENT = ContentPackage(brief=Brief(purpose="report", audience="правление", target_slides=5))
TITLE = TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Итоги года")


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    """Гарнитуры темы, знак шириной в половину кегля — как в `test_layout_fitting`."""
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


def _slide(*blocks: object) -> SlideIR:
    return SlideIR(slide_id="s01", layout_id="L_NARROW", variant="A", blocks=list(blocks))


def test_overflowing_text_is_shortened_until_it_fits(
    narrow: TemplateManifest, fonts: FontLibrary
) -> None:
    """Один абзац чуть длиннее места: `shorten`, и после узла он влезает."""
    text = "Выручка компании выросла за год благодаря новым клиентам и продлениям " * 2
    body = TextBlock(block_id="b", placeholder_idx=NARROW_IDX, role=TextRole.BODY, text=text)

    fitted, notes = _fit_shortening(_slide(TITLE, body), narrow, fonts, CONTENT)

    assert fitted.fit_report["b"].overflow is False
    shortened = next(b for b in fitted.blocks if b.block_id == "b")
    assert isinstance(shortened, TextBlock)
    assert len(shortened.text.split()) < len(text.split())
    assert notes == ["s01/b: текст сокращён, чтобы влезть"]


def test_bullets_are_shortened_item_by_item(narrow: TemplateManifest, fonts: FontLibrary) -> None:
    item = "Отток клиентов снизился, отток клиентов снизился"
    bullets = BulletsBlock(
        block_id="b",
        placeholder_idx=NARROW_IDX,
        items=[BulletItem(text=item), BulletItem(text=item)],
    )
    fitted, notes = _fit_shortening(_slide(TITLE, bullets), narrow, fonts, CONTENT)

    shortened = next(b for b in fitted.blocks if b.block_id == "b")
    assert isinstance(shortened, BulletsBlock)
    assert len(shortened.items) == 2, "пункты сокращаются, а не выбрасываются"
    assert all(len(i.text.split()) < len(item.split()) for i in shortened.items)
    assert notes


def test_text_that_fits_is_left_alone(narrow: TemplateManifest, fonts: FontLibrary) -> None:
    body = TextBlock(block_id="b", placeholder_idx=NARROW_IDX, role=TextRole.BODY, text="Рост")
    fitted, notes = _fit_shortening(_slide(TITLE, body), narrow, fonts, CONTENT)
    assert fitted.blocks[1] == body
    assert notes == []


def test_hopeless_text_is_reported_not_hidden(narrow: TemplateManifest, fonts: FontLibrary) -> None:
    """Сокращение не бесконечно: не влезло за все круги — это видно в заметке."""
    words = " ".join(["Платформа"] * 3)
    body = TextBlock(block_id="b", placeholder_idx=NARROW_IDX, role=TextRole.BODY, text=words)
    tiny = narrow.model_copy(
        update={
            "layouts": [
                layout.model_copy(
                    update={
                        "placeholders": [
                            ph.model_copy(update={"cx": 200_000, "cy": 150_000})
                            if ph.idx == NARROW_IDX
                            else ph
                            for ph in layout.placeholders
                        ]
                    }
                )
                for layout in narrow.layouts
            ]
        }
    )
    fitted, notes = _fit_shortening(_slide(TITLE, body), tiny, fonts, CONTENT)
    assert fitted.fit_report["b"].overflow is True
    assert notes == [] or notes[0].endswith("и всё равно не влез")


def test_placeholder_wins_over_model_coordinates() -> None:
    """Модель отдала и плейсхолдер, и координаты: пишется в плейсхолдер, координаты сброшены."""
    both = TextBlock(
        block_id="b", placeholder_idx=1, role=TextRole.BODY, text="x",
        x=0, y=0, cx=100_000, cy=100_000,
    )
    free = TextBlock(
        block_id="c", role=TextRole.BODY, text="y", x=0, y=0, cx=100_000, cy=100_000
    )
    slide = _into_placeholders(_slide(both, free))
    assert slide.blocks[0].bbox is None and slide.blocks[0].placeholder_idx == 1
    assert slide.blocks[1].bbox is not None, "блок без плейсхолдера сохраняет координаты"


def test_text_that_asks_for_a_split_is_shortened_and_says_so(
    narrow: TemplateManifest, fonts: FontLibrary
) -> None:
    """`split` до записи выполнить некому, а писатель его отвергает: сокращаем и называем это."""
    item = "Отток клиентов снизился, отток клиентов снизился, отток клиентов снизился"
    bullets = BulletsBlock(
        block_id="b", placeholder_idx=NARROW_IDX, items=[BulletItem(text=item)] * 2
    )
    before = fit_slide(_slide(TITLE, bullets), narrow, fonts=fonts).fit_report["b"]
    assert before.strategy == "split"

    fitted, notes = _fit_shortening(_slide(TITLE, bullets), narrow, fonts, CONTENT)
    assert fitted.fit_report["b"].strategy != "split" or fitted.fit_report["b"].overflow is False
    assert notes and "просился на два слайда" in notes[0]


def test_title_may_be_cut_to_two_words_but_body_not_below_three() -> None:
    """Заголовок кеглем не уменьшается — ему разрешено сократиться сильнее тела."""
    from deckforge.pipeline.nodes.fit import _shortened

    title = TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE,
                      text="Существующие инструменты плохо воспроизводят стиль")
    body = TextBlock(block_id="b", role=TextRole.BODY, text="Раз два три")
    for _ in range(6):
        title = _shortened(title) or title
    assert len(title.text.split()) == 2
    assert _shortened(body) is None, "тело короче трёх слов не сокращается"


def test_title_yields_size_when_there_is_nothing_left_to_cut(
    narrow: TemplateManifest, fonts: FontLibrary
) -> None:
    """Прогон 5561f47fdd8f: заголовок из двух слов не влез и уронил запись всей колоды.

    Порядок уступок: сначала слова, и только когда резать нечего — кегль.
    """
    two_words = TextBlock(
        block_id="t", placeholder_idx=NARROW_IDX, role=TextRole.TITLE,
        text="Существующие инструменты",
    )
    fitted, notes = _fit_shortening(_slide(two_words), narrow, fonts, CONTENT)

    result = fitted.fit_report["t"]
    assert result.final_size_pt < narrow.typography(TextRole.TITLE).size_pt
    assert any("кегль заголовка уменьшен" in note for note in notes)


def test_title_that_fits_keeps_its_size(narrow: TemplateManifest, fonts: FontLibrary) -> None:
    """Иерархия заголовка — не расходный материал: влезает, значит остаётся крупным."""
    fitted, notes = _fit_shortening(_slide(TITLE), narrow, fonts, CONTENT)

    assert fitted.fit_report["t"].final_size_pt == narrow.typography(TextRole.TITLE).size_pt
    assert not any("кегль заголовка" in note for note in notes)
