"""«Слайд по рецепту» — одно условие на весь конвейер.

Change `by-recipe-is-one-predicate`, таск RG3 зонтичного предложения
`recipe-is-not-the-models-word` (`docs/agents/tasks-24-09.md`).

До него условие было своё у каждого слоя: вписывание смотрело на непустой `recipe_id`
(`pipeline/nodes/fit.py`), проверка писателя — на пару «`recipe_id` и `zone_id` блока»,
сам писатель — на наличие рецепта в каталоге. Расхождение этих трёх и положило пять
прогонов 24.09: слайд уходил мимо вписывания, проверка молчала, писатель брал кегль
из пустого `fit_report` прямым обращением.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import SlideIR, TextBlock
from deckforge.domain.template import PlaceholderSpec, TemplateManifest
from deckforge.domain.units import EMU_PER_CM
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.nodes.fit import _fit_shortening
from tests.unit.test_layout_fonts import make_font

BODY_IDX = 5

CONTENT = ContentPackage(
    brief=Brief(purpose="report", audience="правление", target_slides=6, language="ru")
)


@pytest.fixture
def fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    """Гарнитуры темы, знак шириной в половину кегля — как в `test_pipeline_fit`."""
    make_font(tmp_path, manifest.theme.fonts.major_latin, advance=500, bold=True)
    make_font(tmp_path, manifest.theme.fonts.minor_latin, advance=500)
    return FontLibrary([tmp_path])


@pytest.fixture
def narrow(manifest: TemplateManifest) -> TemplateManifest:
    """Макет с ещё одним местом под тело: в нём стоит блок `b2`."""
    base = manifest.layout("L07")
    assert base is not None
    placeholder = PlaceholderSpec(
        idx=BODY_IDX, ph_type="BODY", role=TextRole.BODY,
        x=manifest.grid.margins_emu.left, y=5 * EMU_PER_CM, cx=8 * EMU_PER_CM, cy=6 * EMU_PER_CM,
    )
    layout = base.model_copy(
        update={"layout_id": "L_NARROW", "placeholders": [*base.placeholders, placeholder]}
    )
    return manifest.model_copy(update={"layouts": [*manifest.layouts, layout]})


def slide(*blocks: TextBlock, recipe_id: str | None = None) -> SlideIR:
    return SlideIR(
        slide_id="s10",
        layout_id="L_NARROW",
        variant="A",
        recipe_id=recipe_id,
        blocks=list(blocks),
    )


def title(*, zone_id: str | None = None, idx: int | None = None) -> TextBlock:
    return TextBlock(
        block_id="b1", role=TextRole.TITLE, text="Итоги года", zone_id=zone_id,
        placeholder_idx=idx,
    )


def body(*, zone_id: str | None = None, idx: int | None = None) -> TextBlock:
    return TextBlock(
        block_id="b2", role=TextRole.BODY, text="Выручка выросла", zone_id=zone_id,
        placeholder_idx=idx,
    )


# --- предикат ------------------------------------------------------------------


def test_recipe_named_and_every_block_in_a_zone() -> None:
    assert slide(title(zone_id="z5"), body(zone_id="z7"), recipe_id="ex003").by_recipe


def test_no_recipe_means_not_by_recipe() -> None:
    assert not slide(title(idx=0), body(idx=BODY_IDX)).by_recipe


def test_recipe_named_but_no_block_in_a_zone() -> None:
    """Так выглядел `s10` пяти упавших прогонов до правки RG1: рецепт от модели, зон нет."""
    assert not slide(title(idx=0), body(idx=BODY_IDX), recipe_id="ex003").by_recipe


def test_a_mixed_slide_is_not_by_recipe() -> None:
    """Часть блоков в зонах, часть нет: ни вписать по макету, ни скопировать пример.

    Достижимо через слайд-продолжение `split_slide` (`audit/fixes/apply.py`), который
    копирует блоки с `zone_id`, но `recipe_id` не переносит. Сегодня не срабатывает —
    у слайда по рецепту нет блоков-списков, — но условие обязано отвечать и на это.
    """
    assert not slide(title(zone_id="z5"), body(idx=BODY_IDX), recipe_id="ex003").by_recipe


def test_a_slide_without_blocks_is_not_by_recipe() -> None:
    """Пустой список блоков не делает слайд собранным: `all()` на пустом истинен."""
    assert not SlideIR(
        slide_id="s10", layout_id="L_NARROW", variant="A", recipe_id="ex003", blocks=[]
    ).by_recipe


# --- вписывание спрашивает тот же предикат --------------------------------------


def test_fitting_skips_a_real_recipe_slide(
    narrow: TemplateManifest, fonts: FontLibrary
) -> None:
    """Рамки задал автор шаблона — мерить по макету нечего и незачем."""
    source = slide(title(zone_id="z5"), body(zone_id="z7"), recipe_id="ex003")
    fitted, notes = _fit_shortening(source, narrow, fonts, CONTENT)

    assert fitted.blocks == source.blocks
    assert fitted.fit_report == {} and notes == []


def test_fitting_no_longer_skips_a_slide_whose_recipe_is_only_a_name(
    narrow: TemplateManifest, fonts: FontLibrary
) -> None:
    """Вот где ломалось: рецепт назван, а блоки стоят в плейсхолдерах макета.

    Прежнее условие «есть `recipe_id`» пропускало такой слайд мимо вписывания, и писатель
    брал кегль из пустого `fit_report` — `KeyError` по идентификатору блока.
    """
    source = slide(title(idx=0), body(idx=BODY_IDX), recipe_id="ex003")
    fitted, _notes = _fit_shortening(source, narrow, fonts, CONTENT)

    missing = {block.block_id for block in fitted.blocks} - set(fitted.fit_report)
    assert not missing, f"вписывание не посчитало кегль для {sorted(missing)}"


@pytest.mark.parametrize("recipe_id", [None, "ex003"])
def test_the_predicate_alone_decides_whether_fitting_runs(
    recipe_id: str | None, narrow: TemplateManifest, fonts: FontLibrary
) -> None:
    """Пропуск вписывания и `by_recipe` — это одно и то же решение, а не два похожих."""
    source = slide(title(idx=0), body(idx=BODY_IDX), recipe_id=recipe_id)
    fitted, _notes = _fit_shortening(source, narrow, fonts, CONTENT)

    assert source.by_recipe is (fitted.fit_report == {})
