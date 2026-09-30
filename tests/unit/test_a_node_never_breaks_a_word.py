"""Слово в узле схемы не рвётся по слогам. Change `a-node-never-breaks-a-word`.

План Б, круг 2, корень К5. Сценарии — из дельты
`openspec/changes/a-node-never-breaks-a-word/specs/layout-fitting/`.

Education s07, прогон 29.09: «Парси нг докум ентов». Схема стоит в правой колонке макета —
рамка 13 см на четыре шага, узлы по 2,8 см, — а лестница шаблона кончается на 18 pt,
и спуститься вписыванию некуда. Беда не в кегле, а в ширине узла.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.domain.base import BBox
from deckforge.domain.enums import SmartArtPattern, TextRole
from deckforge.domain.slide import SmartArtBlock
from deckforge.domain.template import TemplateManifest
from deckforge.layout.by_design import DesignRules
from deckforge.layout.diagram import diagram_geometry
from deckforge.layout.fitting import fit_smartart, measure_text, process_columns
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.replay import from_fixture

CM = 360_000
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-29"
STEPS = ("Парсинг документов", "Извлечение структуры", "Компьютерное зрение", "LLM-оркестрация")
#: Короткие подписи: такие встают в ряд даже в обычной полосе под заголовком.
SHORT = ("Сбор", "Анализ", "Вёрстка", "Итог")


def narrow() -> BBox:
    """Правая колонка макета «Слайд со спикером»: 13 см ширины, 16,9 см высоты."""
    return BBox(x=19 * CM, y=CM // 2, cx=13 * CM, cy=16 * CM)


def wide() -> BBox:
    """Обычная полоса под заголовком: 30 см ширины."""
    return BBox(x=2 * CM, y=8 * CM, cx=30 * CM, cy=6 * CM)


def block_of(*items: str) -> SmartArtBlock:
    return SmartArtBlock(
        block_id="b01", pattern=SmartArtPattern.PROCESS, items=list(items),
        x=narrow().x, y=narrow().y, cx=narrow().cx, cy=narrow().cy,
    )


def words_fit(items: tuple[str, ...], box: BBox, manifest: TemplateManifest,
              columns: int | None, size_pt: float) -> bool:
    labels = diagram_geometry(
        SmartArtPattern.PROCESS, len(items), box, None, columns=columns
    ).labels
    family = manifest.theme.fonts.minor_latin
    return all(
        measure_text(word, font_family=family, size_pt=size_pt, box=label).lines <= 1
        for text, label in zip(items, labels, strict=True)
        for word in text.split()
    )


def body_size(manifest: TemplateManifest) -> float:
    step = manifest.typography(TextRole.BODY)
    assert step is not None
    return step.size_pt


def test_a_narrow_frame_gets_fewer_steps_in_a_row(manifest: TemplateManifest) -> None:
    """Нарушитель: в колонке четыре шага в ряд дают узел уже самого длинного слова."""
    columns = process_columns(STEPS, narrow(), manifest)

    assert columns < len(STEPS)
    assert words_fit(STEPS, narrow(), manifest, columns, body_size(manifest))
    assert not words_fit(STEPS, narrow(), manifest, len(STEPS), body_size(manifest))


def test_a_wide_frame_keeps_one_row(manifest: TemplateManifest) -> None:
    """Норма: слово встаёт и в один ряд — ряд остаётся один, раскладка прежняя."""
    assert process_columns(SHORT, wide(), manifest) == len(SHORT)
    assert words_fit(SHORT, wide(), manifest, len(SHORT), body_size(manifest))


def test_the_widest_fitting_row_wins(manifest: TemplateManifest) -> None:
    """Норма: берётся наибольшее число столбцов, при котором слово ещё влезает."""
    columns = process_columns(STEPS, narrow(), manifest)

    assert not words_fit(STEPS, narrow(), manifest, columns + 1, body_size(manifest))


def test_arrows_do_not_cross_the_row_break(manifest: TemplateManifest) -> None:
    """Норма: стрелки соединяют соседей одного ряда, через перенос стрелки нет."""
    columns = process_columns(STEPS, narrow(), manifest)
    geometry = diagram_geometry(
        SmartArtPattern.PROCESS, len(STEPS), narrow(), None, columns=columns
    )

    rows = -(-len(STEPS) // columns)
    assert len(geometry.links) == len(STEPS) - rows
    assert geometry.arrows


def test_the_old_path_geometry_is_untouched(manifest: TemplateManifest) -> None:
    """Нарушитель: без числа столбцов раскладка прежняя — эталон прежнего пути держится."""
    plain = diagram_geometry(SmartArtPattern.PROCESS, len(STEPS), narrow(), None)
    same = diagram_geometry(
        SmartArtPattern.PROCESS, len(STEPS), narrow(), None, columns=len(STEPS)
    )

    assert plain.nodes == same.nodes
    assert plain.links == same.links
    assert len({node.y for node in plain.nodes}) == 1, "все шаги в одном ряду"


def test_the_fitting_measures_the_wrapped_geometry(manifest: TemplateManifest) -> None:
    """Норма: вписывание меряет ту же раскладку, которую нарисует писатель."""
    block = block_of(*STEPS)
    design = DesignRules(manifest)

    wrapped = fit_smartart(block, narrow(), manifest, design=design, by_example=True)
    plain = fit_smartart(block, narrow(), manifest, design=design)

    assert not wrapped.overflow, "с переносом рядов схема влезает"
    assert plain.overflow, "в один ряд — нет"


@pytest.mark.parametrize("name", ["education", "vk-tech", "workspace"])
def test_no_word_breaks_in_a_node_on_the_runs(name: str) -> None:
    """Мерило change на прогоне 29.09: разорванных слов в узлах схем нет.

    «До»: Education s05 («Автоматическая») и s07 («Парсинг», «документов», «Извлечение»).
    """
    run = from_fixture(FIXTURES / name)
    design = DesignRules(run.manifest, run.design_system)
    fonts = FontLibrary.default()
    family = run.manifest.theme.fonts.minor_latin

    for slide in run.deck.slides:
        for block in slide.blocks:
            if block.type != "smartart" or block.bbox is None:
                continue
            fit = fit_smartart(
                block, block.bbox, run.manifest, fonts=fonts, design=design, by_example=True
            )
            columns = (
                process_columns(
                    block.items, block.bbox, run.manifest, tile=design.tile(), fonts=fonts
                )
                if block.pattern is SmartArtPattern.PROCESS
                else None
            )
            labels = diagram_geometry(
                block.pattern, len(block.items), block.bbox, design.tile(), columns=columns
            ).labels
            for text, label in zip(block.items, labels, strict=True):
                for word in text.split():
                    lines = measure_text(
                        word, font_family=family, size_pt=fit.final_size_pt,
                        box=label, fonts=fonts,
                    ).lines
                    assert lines <= 1, (
                        f"{name} {slide.slide_id}: «{word}» рвётся в узле"
                    )
