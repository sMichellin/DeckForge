"""Change 5б `no-example-goes-by-design`: слайд без примера верстается дизайн-системой.

Назначение `RecipeAssignment` приедет из потока A (эпик #242, `composition/assign.py`); до его
мержа тесты собирают слайд по подделке той же формы (TEAMWORK §9). Швы — `fit_slide`
и `PptxWriter.write` (колода целиком). Шрифт — синтетический с фиксированной шириной знака:
замер не зависит от шрифтов машины, и эталон прежнего пути совпадает в CI.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from pydantic import BaseModel

from deckforge.domain.content import Brief, ContentPackage, Dataset, Series
from deckforge.domain.enums import CalloutTone, ChartType, SmartArtPattern, TextRole
from deckforge.domain.slide import (
    Block,
    CalloutBlock,
    ChartBlock,
    DeckIR,
    KpiBlock,
    KpiItem,
    QuoteBlock,
    SlideIR,
    SmartArtBlock,
    TableBlock,
    TextBlock,
)
from deckforge.domain.template import TemplateManifest
from deckforge.layout.fitting import fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.parsing import TemplateParser
from deckforge.rendering.writer import PptxWriter
from tests.integration.test_native_objects import build_template
from tests.unit.test_layout_fonts import make_font

GOLDEN = Path(__file__).parents[1] / "fixtures" / "no-example-goes-by-design" / "legacy-slides.json"

STEPS = ["Сбор требований", "Проектирование", "Разработка", "Проверка"]
LONG = [
    "Собрать требования у всех владельцев процесса",
    "Согласовать бюджет и сроки с финансовой службой",
    "Спроектировать архитектуру и интерфейсы модулей",
    "Разработать первую версию и показать заказчику",
    "Провести нагрузочное тестирование на копии данных",
    "Обучить сотрудников поддержки и написать инструкции",
    "Перенести данные из старой системы без простоя",
    "Запустить систему и собрать обратную связь",
]


class RecipeAssignment(BaseModel):
    """Подделка контракта из эпика #242: своего модуля в `composition/**` не заводится."""

    slide_id: str
    recipe_id: str | None
    reason: str
    row_fill: dict[str, int] = {}


def template_and_manifest(tmp_path: Path) -> tuple[Path, TemplateManifest, FontLibrary]:
    template = build_template(tmp_path / "template.pptx")
    manifest = TemplateParser(cache_dir=tmp_path / "cache").parse(template)
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    make_font(fonts_dir, "Deck Sans", advance=500)
    return template, manifest, FontLibrary([fonts_dir])


def content() -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="report", audience="команда", target_slides=12),
        datasets=[
            Dataset(dataset_id="d001", title="Ряд", categories=STEPS,
                    series=[Series(name="s", values=[3.0, 5.0, 2.0, 4.0])]),
            # Серия короче категорий: диаграмму из таких данных не построить.
            Dataset(dataset_id="d002", title="Ряд", categories=STEPS[:3],
                    series=[Series(name="s", values=[1.0, 2.0])]),
        ],
    )


def blocks(manifest: TemplateManifest, *, long_table: bool = True) -> list[Block]:
    """По блоку каждого вида, которому примера нет; рамка — нижние три четверти полей."""
    area = manifest.content_bbox
    box = {"x": area.x, "y": area.y + area.cy // 4, "cx": area.cx, "cy": area.cy * 3 // 4}
    out: list[Block] = [
        *[SmartArtBlock(block_id=f"sa-{p.value}", pattern=p, items=STEPS, **box)
          for p in SmartArtPattern],
        SmartArtBlock(block_id="sa-long", pattern=SmartArtPattern.PROCESS, items=LONG, **box),
        KpiBlock(block_id="kpi", items=[KpiItem(value=v, label=s) for v, s in
                                        zip(("37 %", "2×", "10 мин"), STEPS, strict=False)],
                 **box),
        QuoteBlock(block_id="quote", text=LONG[0], author="Заказчик", **box),
        CalloutBlock(block_id="callout", text=LONG[1], tone=CalloutTone.RISK, **box),
        ChartBlock(block_id="chart", chart_type=ChartType.CLUSTERED_COLUMN, dataset_ref="d001",
                   **box),
        ChartBlock(block_id="chart-bad", chart_type=ChartType.CLUSTERED_COLUMN,
                   dataset_ref="d002", **box),
        TableBlock(block_id="table", header=["Этап", "Итог"],
                   rows=[[s, t] for s, t in zip(STEPS, LONG, strict=False)], **box),
    ]
    if long_table:
        out.append(TableBlock(block_id="table-long", header=["Этап", "Итог"],
                              rows=[[s, t] for s, t in zip(STEPS * 8, LONG * 4, strict=True)],
                              **box))
    return out


def slide_for(
    assignment: RecipeAssignment, block: Block, manifest: TemplateManifest
) -> SlideIR:
    """Слайд по назначению: примера нет — макет только с заголовком, блок вне зон."""
    layout = min(
        (spec for spec in manifest.layouts
         if any(p.idx == 0 and p.role is TextRole.TITLE for p in spec.placeholders)),
        key=lambda spec: len(spec.placeholders),
    )
    return SlideIR(
        slide_id=assignment.slide_id, layout_id=layout.layout_id, variant="A",
        recipe_id=assignment.recipe_id,
        blocks=[TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE,
                          text="Слайд без примера"), block],
    )


def slide_xml(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        return {
            name: z.read(name).decode("utf-8")
            for name in z.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        }


def legacy_deck_xml(tmp_path: Path) -> dict[str, str]:
    """Колода без рецептов прежним путём: вписывание и писатель без параметра пути сборки.

    Длинной таблицы здесь нет — прежний путь отказывает в записи всей колоды с ней."""
    template, manifest, fonts = template_and_manifest(tmp_path)
    package = content()
    slides = [
        fit_slide(
            slide_for(RecipeAssignment(slide_id=f"s{i:02d}", recipe_id=None, reason="нет примера"),
                      block, manifest),
            manifest, fonts=fonts, content=package,
        )
        for i, block in enumerate(blocks(manifest, long_table=False), start=1)
    ]
    deck = DeckIR(deck_id="d1", variant="A", template_id=manifest.template_id, seed=7,
                  slides=slides)
    out = PptxWriter(template, manifest, fonts=fonts).write(deck, tmp_path / "deck.pptx", package)
    return slide_xml(out)


def test_legacy_path_is_unchanged_byte_for_byte(tmp_path: Path) -> None:
    """Эталон снят до правки кода (22a): без параметра пути сборки файл прежний."""
    assert legacy_deck_xml(tmp_path) == json.loads(GOLDEN.read_text(encoding="utf-8"))
