"""HTML-экспорт не падает и не теряет текст на слайде по рецепту.

Change `html-export-keeps-the-zone-text`, таск RG16 (`docs/agents/tasks-24-09.md`).

Прогон `5cf2705fc173` (24.09, `d4e0d60`) впервые дошёл до стадии `export` — прежде
падал раньше, в `render`, — и упал там:
`AttributeError: 'NoneType' object has no attribute 'bbox'`. У блока, стоящего в зоне
рецепта, нет ни координат, ни `placeholder_idx`: рамку ему дал автор шаблона.
`layout.placeholder(None)` возвращает `None`. Таких блоков в прогоне было четырнадцать
на девяти слайдах, и колода к тому моменту была уже записана.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from deckforge.domain.enums import TextRole
from deckforge.domain.slide import DeckIR, FitResult, SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.export.html import export_html

#: Тексты зон — те же, что были на `s02` прогона `5cf2705fc173`.
TITLE = "Проблема: ручная адаптация шаблонов замедляет работу"
BODY = "Создание презентаций в фирменном стиле требует участия дизайнеров"
EXTRA = "AI-инструменты хуже справляются с воспроизведением структуры"


def recipe_deck(manifest: TemplateManifest) -> DeckIR:
    """Слайд по рецепту: рецепт назван, каждый блок в зоне, отчёта о вписывании нет."""
    slide = SlideIR(
        slide_id="s02",
        layout_id="L07",
        variant="A",
        recipe_id="ex005",
        blocks=[
            TextBlock(block_id="b01", role=TextRole.TITLE, text=TITLE, zone_id="z441"),
            TextBlock(block_id="b02", role=TextRole.BODY, text=BODY, zone_id="z442"),
            TextBlock(block_id="b02-1", role=TextRole.BODY, text=EXTRA, zone_id="z446"),
        ],
    )
    return DeckIR(
        deck_id="d", variant="A", template_id=manifest.template_id, seed=1, slides=[slide]
    )


@pytest.fixture
def html(manifest: TemplateManifest, tmp_path: Path) -> str:
    out = export_html(recipe_deck(manifest), manifest, tmp_path / "deck.html")
    return out.read_text(encoding="utf-8")


def test_export_does_not_fail(html: str) -> None:
    """Само воспроизведение: до правки здесь был `AttributeError`."""
    assert html.startswith("<!doctype html>") or html.lstrip().startswith("<!")


def test_every_zone_text_is_in_the_document(html: str) -> None:
    """Пропустить блок без рамки было бы дёшево — и html соврал бы про колоду."""
    for text in (TITLE, BODY, EXTRA):
        # Неразрывные пробелы html ставит по правилу Т4 — текст зоны от этого не меняется.
        assert text in html.replace(" ", " "), f"текст зоны потерян: {text!r}"


def test_zone_blocks_go_into_one_flow_strip(html: str) -> None:
    """Место блокам даёт полоса в области контента, а не их собственные координаты."""
    assert 'class="zones"' in html
    strip = re.search(r'<div class="zones" style="([^"]*)">(.*?)</div>\s*</section>', html, re.S)
    assert strip is not None, "полосы зон в документе нет"
    assert "left:" in strip.group(1) and "width:" in strip.group(1)
    assert strip.group(2).count('class="block') == 3


def test_a_zone_block_has_no_coordinates_of_its_own(html: str) -> None:
    """Инлайновый стиль сильнее класса: выпиши координаты — и блок выйдет из потока."""
    blocks = re.findall(r'<div class="block[^"]*" data-block="(b0[^"]*)" style="([^"]*)"', html)
    assert {block_id for block_id, _ in blocks} == {"b01", "b02", "b02-1"}
    for block_id, style in blocks:
        assert "left:" not in style and "width:" not in style, f"{block_id}: рамка выписана"


def test_text_is_sized_by_the_template_scale(html: str, manifest: TemplateManifest) -> None:
    """Отчёта о вписывании у такого блока нет, а `font-size: 0` — это невидимый текст."""
    sizes = re.findall(r'data-block="b0[^"]*" style="[^"]*font-size: ([0-9.]+)cqw', html)
    assert len(sizes) == 3
    assert all(float(size) > 0 for size in sizes), f"кегль нулевой: {sizes}"


def test_an_ordinary_slide_is_still_placed_absolutely(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    """Слайд без рецепта не меняется ни на строку: координаты у его блоков на месте."""
    deck = recipe_deck(manifest)
    plain = deck.slides[0].model_copy(
        update={
            "recipe_id": None,
            "blocks": [
                TextBlock(block_id="b01", placeholder_idx=0, role=TextRole.TITLE, text=TITLE)
            ],
            "fit_report": {
                "b01": FitResult(
                    final_size_pt=manifest.typography(TextRole.TITLE).size_pt  # type: ignore[union-attr]
                )
            },
        }
    )
    out = export_html(
        deck.model_copy(update={"slides": [plain]}), manifest, tmp_path / "plain.html"
    )
    html = out.read_text(encoding="utf-8")

    assert 'class="zones"' not in html
    style = re.search(r'data-block="b01" style="([^"]*)"', html)
    assert style is not None and "left:" in style.group(1)
