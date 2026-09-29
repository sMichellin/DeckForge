"""Переполненная таблица или схема — находка аудита. Change `the-overflowing-table-is-found`,
задача потоку C от тимлида в #245 после #259 (план Б, 5б).

На пути `by_example` слайд без примера не сплющивает не влезший блок: таблица и схема
пишутся своим видом «как есть», переполнение названо только в `degradations`, а
`layout.text_overflow` смотрит лишь текст и списки. Проверка `layout.object_overflow` меряет
записанный файл. Правило 7: нарушитель и норма.

Сценарии — из дельты `openspec/changes/the-overflowing-table-is-found/specs/`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from deckforge.audit.deterministic.layout import object_overflow
from deckforge.audit.registry import CheckUnavailable
from deckforge.composition.assign import RecipeAssignment
from deckforge.domain.content import ContentPackage, Dataset, Series
from deckforge.domain.enums import ChartType, SmartArtPattern
from deckforge.domain.slide import Block, ChartBlock, DeckIR, SmartArtBlock, TableBlock
from deckforge.domain.template import TemplateManifest
from deckforge.layout.fitting import fit_slide
from deckforge.rendering.writer import PptxWriter
from tests.unit._audit_builders import context_for
from tests.unit.test_no_example_goes_by_design import (
    LONG,
    STEPS,
    content,
    slide_for,
    template_and_manifest,
)

CHECK = "layout.object_overflow"
Make = Callable[[dict[str, int]], Block]


def _box(manifest: TemplateManifest) -> dict[str, int]:
    """Нижние три четверти полей шаблона — место блока, как в тестах 5б."""
    area = manifest.content_bbox
    return {"x": area.x, "y": area.y + area.cy // 4, "cx": area.cx, "cy": area.cy * 3 // 4}


def _package() -> ContentPackage:
    """Контент 5б плюс длинный битый ряд: диаграмму не построить, таблица не влезет."""
    base = content()
    categories = [f"{step} {n}" for n in range(8) for step in STEPS]
    broken = Dataset(dataset_id="d003", title="Длинный ряд", categories=categories,
                     series=[Series(name="s", values=[1.0, 2.0])])
    return base.model_copy(update={"datasets": [*base.datasets, broken]})


def write(tmp_path: Path, make: Make, *, by_example: bool = True) -> tuple[list, DeckIR, Any]:
    """Слайд без примера с одним блоком: вписывание → запись → проверка по файлу."""
    template, manifest, fonts = template_and_manifest(tmp_path)
    package = _package()
    assignment = RecipeAssignment(slide_id="s01", recipe_id=None, reason="примера нет")
    slide = fit_slide(slide_for(assignment, make(_box(manifest)), manifest), manifest,
                      fonts=fonts, content=package, by_example=by_example)
    deck = DeckIR(deck_id="d1", variant="A", template_id=manifest.template_id, seed=7,
                  slides=[slide])
    path = PptxWriter(template, manifest, fonts=fonts, by_example=by_example).write(
        deck, tmp_path / "deck.pptx", package
    )
    ctx = context_for(CHECK, deck, manifest, content=package, deck_path=path)
    return list(object_overflow(ctx)), deck, ctx


def long_table(box: dict[str, int]) -> Block:
    return TableBlock(block_id="table-long", header=["Этап", "Итог"],
                      rows=[[s, t] for s, t in zip(STEPS * 8, LONG * 4, strict=True)], **box)


def long_process(box: dict[str, int]) -> Block:
    """Восемь длинных шагов в узкой колонке: не влезают ни в один ряд, ни в несколько.

    Колонка нужна с change `a-node-never-breaks-a-word` (круг 2, К5): шаги процесса
    переносятся в ряды так, чтобы слово вставало в узел целиком, и в полную ширину полей
    эти восемь шагов теперь влезают. Проверка `layout.object_overflow` про другое —
    про схему, которой места нет и с переносом, — и колонка в четверть ширины даёт
    ровно такой случай.
    """
    narrow = {**box, "cx": box["cx"] // 4}
    return SmartArtBlock(
        block_id="sa-long", pattern=SmartArtPattern.PROCESS, items=LONG, **narrow
    )


def test_a_long_table_written_as_is_is_a_finding(tmp_path: Path) -> None:
    """Нарушитель: 32 строки таблицы на пути `by_example` записаны таблицей выше своего места."""
    findings, _, _ = write(tmp_path, long_table)

    assert [f.block_id for f in findings] == ["table-long"]
    assert int(findings[0].evidence["frame_cy"]) > int(findings[0].evidence["box_cy"])


def test_a_table_that_fits_is_not_a_finding(tmp_path: Path) -> None:
    """Норма: таблица из четырёх строк влезла в своё место."""
    findings, deck, _ = write(tmp_path, lambda box: TableBlock(
        block_id="table", header=["Этап", "Итог"],
        rows=[[s, t] for s, t in zip(STEPS, LONG, strict=False)], **box))

    assert not deck.slides[0].fit_report["table"].overflow, "замер не тот: таблица не влезла"
    assert findings == []


def test_a_chart_that_became_a_long_table_is_a_finding(tmp_path: Path) -> None:
    """Нарушитель: диаграмму не построить из данных — писатель записал таблицу выше места."""
    findings, _, _ = write(tmp_path, lambda box: ChartBlock(
        block_id="chart-bad", chart_type=ChartType.CLUSTERED_COLUMN, dataset_ref="d003", **box))

    assert [f.block_id for f in findings] == ["chart-bad"]
    assert "Диаграмма" in findings[0].message


def test_an_overflowing_smartart_written_as_is_is_a_finding(tmp_path: Path) -> None:
    """Нарушитель: подписи длинной схемы не влезли, а схема записана группой как есть."""
    findings, deck, _ = write(tmp_path, long_process)

    assert deck.slides[0].fit_report["sa-long"].overflow, "замер не тот: схема влезла"
    assert [(f.block_id, f.evidence["source"]) for f in findings] == [("sa-long", "fit_report")]


def test_a_smartart_that_fits_is_not_a_finding(tmp_path: Path) -> None:
    """Норма: четыре коротких шага влезли."""
    findings, _, _ = write(tmp_path, lambda box: SmartArtBlock(
        block_id="sa", pattern=SmartArtPattern.PROCESS, items=STEPS, **box))

    assert findings == []


def test_a_smartart_replaced_by_a_list_is_not_this_finding(tmp_path: Path) -> None:
    """Норма: прежний путь заменил не влезшую схему списком — вылета схемы на слайде нет,
    список — забота `layout.text_overflow`."""
    findings, deck, _ = write(tmp_path, long_process, by_example=False)

    assert deck.slides[0].fit_report["sa-long"].overflow, "замер не тот: схема влезла"
    assert findings == []


def test_without_the_file_the_check_is_skipped(tmp_path: Path) -> None:
    """Файла нет — «не мерили»: по IR не видно, каким видом блок записан."""
    _, _, ctx = write(tmp_path, long_table)

    with pytest.raises(CheckUnavailable):
        list(object_overflow(replace(ctx, deck_path=None)))
