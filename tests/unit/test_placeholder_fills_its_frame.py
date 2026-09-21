"""Тело в плейсхолдере занимает свою рамку. Change `placeholder-fills-its-frame` (B11).

Прогон VK Education `6b1d9e82b612`: тело макета отдано во всю ширину и на две трети
высоты, а три пункта заняли верхнюю треть — ниже пустая полоса в 0,43–0,53 высоты (C9).
Рост кегля по шкале шаблона был сделан в change `free-block-grows-to-its-space`, но
только для свободных блоков: `_grows_to_its_space` отказывал всему, у чего есть
`placeholder_idx`.

Отказ был осторожностью, а не правилом: кегль плейсхолдера мы и так меняем — вниз,
когда текст не влезает (`allow_shrink`). Шаблоны кейса это прямо разрешают, помечая
тело `normAutofit`. Асимметрия «вниз можно, вверх нельзя» ничем не обоснована.

Растёт только **тело**. Подпись, колонтитул и заголовок набраны кеглем, который несёт
иерархию слайда: у VK Education подпись под фото — полоса высотой в строку, и рост
превратил бы её в второй заголовок.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.enums import TextRole
from deckforge.domain.rules import next_size_down
from deckforge.domain.slide import BulletItem, BulletsBlock, TextBlock
from deckforge.domain.template import PlaceholderSpec, TemplateManifest
from deckforge.domain.units import EMU_PER_CM
from deckforge.layout.fitting import fit_block
from deckforge.layout.fonts import FontLibrary
from tests.unit.test_layout_fonts import make_font

BODY_IDX = 1
CAPTION_IDX = 7


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=500, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=500)
    return FontLibrary([tmp_path])


@pytest.fixture
def with_caption(manifest: TemplateManifest) -> TemplateManifest:
    """Макет с подписью-полосой рядом с телом: так устроен «1 фото + подпись» VK Education."""
    base = manifest.layout("L07")
    assert base is not None
    caption = PlaceholderSpec(
        idx=CAPTION_IDX, ph_type="BODY", role=TextRole.CAPTION,
        x=manifest.grid.margins_emu.left, y=15 * EMU_PER_CM,
        cx=12 * EMU_PER_CM, cy=1 * EMU_PER_CM,
    )
    layout = base.model_copy(
        update={"layout_id": "L_CAPTION", "placeholders": [*base.placeholders, caption]}
    )
    return manifest.model_copy(update={"layouts": [*manifest.layouts, layout]})


def bullets_in_body(manifest: TemplateManifest, *texts: str) -> BulletsBlock:
    return BulletsBlock(
        block_id="b",
        placeholder_idx=BODY_IDX,
        role=TextRole.BODY,
        items=[BulletItem(text=text) for text in texts],
    )


def test_short_list_in_the_body_grows_up_the_ladder(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Нарушитель B11: три пункта в теле на пол-слайда оставались кеглем роли."""
    layout = manifest.layout("L07")
    assert layout is not None
    body_step = manifest.typography(TextRole.BODY)
    assert body_step is not None

    grown = fit_block(
        bullets_in_body(manifest, "Первый довод", "Второй довод", "Третий довод"),
        layout, manifest, fonts=fonts,
    )

    assert grown.final_size_pt > body_step.size_pt, "список остался жаться к верху рамки"
    assert grown.final_size_pt in manifest.size_ladder_pt, "кегль вне шкалы шаблона"
    assert grown.strategy == "grow"
    assert grown.overflow is False


def test_growth_in_the_placeholder_stops_below_the_title(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Тело вровень с заголовком стирает иерархию — потолок тот же, что у свободного блока."""
    layout = manifest.layout("L07")
    assert layout is not None
    title_step = manifest.typography(TextRole.TITLE)
    assert title_step is not None
    cap = next_size_down(manifest, title_step.size_pt) or title_step.size_pt

    grown = fit_block(bullets_in_body(manifest, "Два слова"), layout, manifest, fonts=fonts)

    assert grown.final_size_pt <= cap


def test_the_caption_band_does_not_grow(
    with_caption: TemplateManifest, fonts: FontLibrary
) -> None:
    """Норма: подпись под фото — не тело. Её кегль задаёт иерархию, а не объём текста."""
    layout = with_caption.layout("L_CAPTION")
    assert layout is not None
    caption_step = with_caption.typography(TextRole.CAPTION) or with_caption.typography(
        TextRole.BODY
    )
    assert caption_step is not None

    result = fit_block(
        TextBlock(block_id="c", placeholder_idx=CAPTION_IDX, role=TextRole.CAPTION, text="Рис. 1"),
        layout, with_caption, fonts=fonts,
    )

    assert result.strategy != "grow"
    assert result.final_size_pt <= caption_step.size_pt


def test_the_title_placeholder_still_does_not_grow(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Норма: заголовок не растёт ни в плейсхолдере, ни свободным блоком."""
    layout = manifest.layout("L07")
    assert layout is not None
    title_step = manifest.typography(TextRole.TITLE)
    assert title_step is not None

    result = fit_block(
        TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Итог"),
        layout, manifest, fonts=fonts,
    )

    assert result.strategy != "grow"
    assert result.final_size_pt <= title_step.size_pt


def test_an_explicit_size_is_not_overridden(
    manifest: TemplateManifest, fonts: FontLibrary
) -> None:
    """Норма: кегль, назначенный явно, назначили не просто так."""
    layout = manifest.layout("L07")
    assert layout is not None
    body_step = manifest.typography(TextRole.BODY)
    assert body_step is not None
    assigned = next_size_down(manifest, body_step.size_pt) or body_step.size_pt

    result = fit_block(
        TextBlock(
            block_id="b", placeholder_idx=BODY_IDX, role=TextRole.BODY,
            text="Коротко", size_pt=assigned,
        ),
        layout, manifest, fonts=fonts,
    )

    assert result.strategy != "grow"
    assert result.final_size_pt == assigned


def test_a_full_body_is_left_alone(manifest: TemplateManifest, fonts: FontLibrary) -> None:
    """Норма: расти некуда — текст и так занимает рамку."""
    layout = manifest.layout("L07")
    assert layout is not None
    long_text = " ".join(["Довод о пользе внедрения и его измеримом результате"] * 30)

    result = fit_block(
        TextBlock(block_id="b", placeholder_idx=BODY_IDX, role=TextRole.BODY, text=long_text),
        layout, manifest, fonts=fonts,
    )

    assert result.strategy != "grow"
