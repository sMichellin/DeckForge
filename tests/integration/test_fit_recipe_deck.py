"""Колода целиком по рецептам настоящего шаблона проходит вписывание (RG29).

Прогоны 24.09: `recipe_share` = 1.0 на всех трёх шаблонах кейса, а узел `fit` каждый
такой слайд пропускал. Здесь — каждый рецепт каталога шаблона слайдом, текст в каждой
зоне, и узел `fit` целиком (`_fit_shortening`): без исключений, и у каждого текстового
блока в зоне с рамкой есть запись `fit_report`.

Правило 10: тот же прогон на холодном корпусе (`tests/e2e/cold_corpus.py`). Шаблоны
LibreOffice слайдов-примеров не везут, и каталог рецептов у них пуст — такой шаблон
пропускается с названной причиной, а не зеленеет впустую.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import DesignSystem, TypeLevel
from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.layout.by_design import DesignRules
from deckforge.parsing import TemplateParser
from deckforge.pipeline.nodes.fit import _fit_shortening
from tests.case_templates import case_template
from tests.e2e.cold_corpus import cold_templates

CASE_TEMPLATES = [
    "VK Tech шаблон.pptx",
    "VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx",
    "Шаблон презентации VK Education.pptx",
]

CONTENT = ContentPackage(brief=Brief(purpose="report", audience="правление", target_slides=5))

#: Текст зоны — по её вместимости, как его режет композиция, но не короче двух слов.
PHRASE = (
    "Анализ шаблона, извлечение композиций и автоматическая генерация презентаций "
    "в фирменном стиле компании без ручной вёрстки"
)


def _text(capacity: int) -> str:
    all_words = PHRASE.split()
    words = all_words[:2]
    for word in all_words[2:]:
        if len(" ".join([*words, word])) > capacity:
            break
        words.append(word)
    return " ".join(words)


def _deck(manifest: TemplateManifest, ds: DesignSystem) -> list[SlideIR]:
    slides = []
    for number, recipe in enumerate(ds.recipes, start=1):
        blocks = [
            TextBlock(
                block_id=f"b{index}",
                role=TextRole.TITLE if zone.role is TypeLevel.SLIDE_TITLE else TextRole.BODY,
                text=_text(zone.capacity_chars),
                zone_id=zone.zone_id,
            )
            for index, zone in enumerate(recipe.zones)
        ]
        if blocks:
            slides.append(SlideIR(
                slide_id=f"s{number:02d}", layout_id=manifest.layouts[0].layout_id,
                variant="A", recipe_id=recipe.recipe_id, blocks=blocks,
            ))
    return slides


def _fits_every_framed_zone(template: Path) -> None:
    manifest = TemplateParser().parse(template, use_cache=False)
    ds = derive(manifest)
    slides = _deck(manifest, ds)
    if not slides:
        pytest.skip(f"у шаблона {template.name} нет слайдов-примеров — каталог рецептов пуст")
    design = DesignRules(manifest, ds)
    zones = {r.recipe_id: {z.zone_id: z for z in r.zones} for r in ds.recipes}

    framed = kept = 0
    for slide in slides:
        fitted, _ = _fit_shortening(slide, manifest, None, CONTENT, design)
        assert fitted.by_recipe or not fitted.blocks
        after = {block.block_id: block for block in fitted.blocks}
        for block in fitted.blocks:
            assert block.bbox is None
            assert block.zone_id is not None and slide.recipe_id is not None
            if zones[slide.recipe_id][block.zone_id].has_frame:
                framed += 1
                assert block.block_id in fitted.fit_report, f"{slide.slide_id}/{block.block_id}"
        # Текст по вместимости зоны — тот, что пропускает композиция, — вписывание не снимает.
        # Сокращать может: `capacity_chars` считает знаки, а вписывание — слова полужирным
        # и строки (VK Tech 20 из 156, VK Education 45 из 96 на замене гарнитур, см. proposal).
        for block in slide.blocks:
            zone = zones[slide.recipe_id][block.zone_id or ""]
            if zone.has_frame and isinstance(block, TextBlock) and (
                len(block.text) <= zone.capacity_chars
            ):
                kept += 1
                fitted_block = after.get(block.block_id)
                assert isinstance(fitted_block, TextBlock), f"{slide.slide_id}/{block.block_id}"
                assert fitted_block.text, f"{slide.slide_id}/{block.block_id}"
    assert framed > 0
    assert kept > 0
    assert derive(manifest).recipes == ds.recipes


@pytest.mark.slow
@pytest.mark.parametrize("name", CASE_TEMPLATES)
def test_a_deck_by_recipes_is_fitted_zone_by_zone(name: str) -> None:
    _fits_every_framed_zone(case_template(name))


@pytest.mark.cold
@pytest.mark.slow
@pytest.mark.skipif(
    not cold_templates(), reason="нет холодных шаблонов: ни в cold/, ни от LibreOffice"
)
@pytest.mark.parametrize("template", cold_templates(), ids=lambda p: p.name)
def test_a_deck_by_recipes_is_fitted_on_a_cold_template(template: Path) -> None:
    _fits_every_framed_zone(template)


#: Текст карточки из приёмки RG29 (VK Tech s07–s09): на превью снят целиком.
CARD = "Анализ шаблона и извлечение дизайн-системы"


@pytest.mark.slow
@pytest.mark.parametrize("recipe_id", ["ex014", "ex026", "ex048"])
def test_a_card_in_a_frame_lower_than_its_line_keeps_its_text(recipe_id: str) -> None:
    """D02 (§11, T14): рамка зоны ниже одной строки собственного кегля — якорь, не коробка.

    У карточек VK Tech рамки высотой 12–13 pt при кегле зоны 10,5–18 pt: ни одна строка
    своего кегля в них не встаёт, а текст у автора растёт вниз. Мерить такую рамку
    по высоте — значит не вписать ничего: приёмка сняла все карточки s07–s09.
    Текст в каждой зоне первой ступени каждого повтора, узел `fit` целиком.
    """
    manifest = TemplateParser().parse(case_template("VK Tech шаблон.pptx"), use_cache=False)
    ds = derive(manifest)
    recipe = next(r for r in ds.recipes if r.recipe_id == recipe_id)
    firsts = {}
    for zone in recipe.zones:
        if zone.repeat is not None and zone.has_frame:
            firsts.setdefault(zone.repeat, zone)
    blocks = [
        TextBlock(block_id=f"b{repeat}", role=TextRole.BODY, text=CARD, zone_id=zone.zone_id)
        for repeat, zone in sorted(firsts.items())
    ]
    slide = SlideIR(
        slide_id="s07", layout_id=manifest.layouts[0].layout_id, variant="A",
        recipe_id=recipe_id, blocks=blocks,
    )

    fitted, notes = _fit_shortening(slide, manifest, None, CONTENT, DesignRules(manifest, ds))

    assert len(blocks) >= 3
    assert [b.text for b in fitted.blocks if isinstance(b, TextBlock)] == [CARD] * len(blocks)
    assert not any(" снят — " in note or "сокращён" in note for note in notes), notes
