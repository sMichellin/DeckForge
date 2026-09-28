"""Change 5б `no-example-goes-by-design`: слайд без примера верстается дизайн-системой.

Слайд собирается по настоящему назначению `RecipeAssignment` потока A (`composition/assign.py`,
#248). Швы — `fit_slide`, `PptxWriter.write` (колода целиком), `export_html` и общие для pptx
и html `SlideDegrader`/`SlideValidator`. Шрифт — синтетический с фиксированной шириной знака:
замер не зависит от шрифтов машины, и эталон прежнего пути совпадает в CI.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

from deckforge.composition.assign import RecipeAssignment
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
from deckforge.export.html import export_html
from deckforge.layout.fitting import fit_slide
from deckforge.layout.fonts import FontLibrary
from deckforge.parsing import TemplateParser
from deckforge.rendering.writer import PptxWriter, SlideDegrader, SlideValidator, WriterError
from tests.case_templates import case_template
from tests.integration.test_native_objects import build_template
from tests.unit.test_layout_fonts import make_font

FIXTURES = Path(__file__).parents[1] / "fixtures" / "no-example-goes-by-design"
GOLDEN = FIXTURES / "legacy-slides.json"
GOLDEN_COLD = FIXTURES / "legacy-slides-cold-focus.json"

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


def template_and_manifest(
    tmp_path: Path, template: Path | None = None
) -> tuple[Path, TemplateManifest, FontLibrary]:
    """Синтетический шаблон или данный (холодный); шрифт — всегда синтетический."""
    template = template or build_template(tmp_path / "template.pptx")
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


def legacy_deck_xml(tmp_path: Path, template: Path | None = None) -> dict[str, str]:
    """Колода без рецептов прежним путём: вписывание и писатель без параметра пути сборки.

    Длинной таблицы здесь нет — прежний путь отказывает в записи всей колоды с ней."""
    template, manifest, fonts = template_and_manifest(tmp_path, template)
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


def test_legacy_path_is_unchanged_on_a_cold_template(tmp_path: Path) -> None:
    """Второй эталон (22a) — на холодном шаблоне, снят кодом `origin/plan-b` до правки.
    Холодный корпус в git не коммитится (`cold/` в `.gitignore`): нет файла — пропуск."""
    template = case_template("cold/Focus.pptx")
    assert legacy_deck_xml(tmp_path, template) == json.loads(
        GOLDEN_COLD.read_text(encoding="utf-8")
    )


def by_example(tmp_path: Path, block_id: str) -> tuple[PptxWriter, str]:
    """Слайд без примера путём `by_example`: назначение без рецепта → вписывание → запись."""
    template, manifest, fonts = template_and_manifest(tmp_path)
    package = content()
    block = next(b for b in blocks(manifest) if b.block_id == block_id)
    assignment = RecipeAssignment(slide_id="s01", recipe_id=None, reason="примера нет")
    slide = fit_slide(slide_for(assignment, block, manifest), manifest, fonts=fonts,
                      content=package, by_example=True)
    deck = DeckIR(deck_id="d1", variant="A", template_id=manifest.template_id, seed=7,
                  slides=[slide])
    writer = PptxWriter(template, manifest, fonts=fonts, by_example=True)
    out = writer.write(deck, tmp_path / "deck.pptx", package)
    (xml,) = slide_xml(out).values()
    return writer, xml


def flattened_or_dropped(writer: PptxWriter) -> list[str]:
    """Потери блока: сплющен в текст или снят. Диаграмма → таблица — нативный объект, не текст."""
    return [d for d in writer.degradations if "→ буллеты" in d or "→ маркир" in d or "убран" in d]


def test_hierarchy_without_example_is_a_component_not_a_list(tmp_path: Path) -> None:
    """Иерархии нет раскладки на прежнем пути — писатель сплющивал её в буллеты (22)."""
    writer, xml = by_example(tmp_path, "sa-hierarchy")
    assert flattened_or_dropped(writer) == []
    assert 'name="Компонент hierarchy"' in xml


#: Вид блока → по чему в XML слайда видно, что он записан своим объектом, а не текстом.
NATIVE = {
    **{f"sa-{p.value}": f'name="Компонент {p.value}"' for p in SmartArtPattern},
    "kpi": ">37",
    "quote": "Заказчик",
    "callout": 'name="Callout risk"',
    "chart": "<c:chart ",
    "chart-bad": "<a:tbl>",
    "table": "<a:tbl>",
}


@pytest.mark.parametrize("block_id", sorted(NATIVE))
def test_every_kind_without_example_keeps_its_own_object(tmp_path: Path, block_id: str) -> None:
    """Ни один вид блока слайда без примера не снят и не сплющен в текст (22, R24).
    Диаграмма из битых данных становится таблицей — нативным объектом, не буллетами."""
    writer, xml = by_example(tmp_path, block_id)
    assert flattened_or_dropped(writer) == []
    assert NATIVE[block_id] in xml


@pytest.mark.parametrize(("block_id", "native"), [
    ("sa-long", 'name="Компонент process"'),
    ("table-long", "<a:tbl>"),
])
def test_overflow_is_named_not_flattened(tmp_path: Path, block_id: str, native: str) -> None:
    """Не влезшая схема или таблица остаётся своим видом, переполнение названо: прежний путь
    сплющивал схему в буллеты, а длинную таблицу снимал отказом записи всей колоды."""
    writer, xml = by_example(tmp_path, block_id)
    assert flattened_or_dropped(writer) == []
    assert native in xml
    assert any("переполнен" in d for d in writer.degradations)


def test_fitting_measures_every_pattern_only_on_the_by_example_path(tmp_path: Path) -> None:
    """Вписывание (layout-fitting): иерархия меряется по своей раскладке на пути `by_example`;
    без параметра — пропускается, как до change (писатель прежнего пути заменит её списком)."""
    _, manifest, fonts = template_and_manifest(tmp_path)
    block = next(b for b in blocks(manifest) if b.block_id == "sa-hierarchy")
    slide = slide_for(RecipeAssignment(slide_id="s01", recipe_id=None, reason="примера нет"),
                      block, manifest)
    assert "sa-hierarchy" in fit_slide(slide, manifest, fonts=fonts, by_example=True).fit_report
    assert "sa-hierarchy" not in fit_slide(slide, manifest, fonts=fonts).fit_report


@pytest.mark.parametrize(("recipe_id", "as_before"), [(None, False), ("r1", True)])
def test_only_the_slide_without_example_is_relaxed(
    tmp_path: Path, recipe_id: str | None, as_before: bool
) -> None:
    """Путь `by_example` ослабляет проверку и деградацию только слайду без рецепта: рецептный
    слайд того же пути с блоком вне зон отказывает из-за переполнения и сплющивает длинную
    таблицу, как раньше."""
    _, manifest, fonts = template_and_manifest(tmp_path)
    package = content()
    block = next(b for b in blocks(manifest) if b.block_id == "table-long")
    assignment = RecipeAssignment(slide_id="s01", recipe_id=recipe_id, reason="назначение")
    slide = fit_slide(slide_for(assignment, block, manifest), manifest, fonts=fonts,
                      content=package, by_example=True)
    problems = SlideValidator(manifest, by_example=True).problems(slide, package)
    degrader = SlideDegrader(manifest, fonts, by_example=True)
    degrader.degrade(slide, package)
    assert any("переполнение" in p for p in problems) is as_before
    assert any("таблица → буллеты" in d for d in degrader.degradations) is as_before


def test_writer_refuses_a_diagram_the_fitting_path_did_not_measure(tmp_path: Path) -> None:
    """Путь называют два независимых флага — вписывания и писателя. Вписывание прежним путём
    иерархию не меряет; писатель пути `by_example` не пишет схему без замера молча, а отказывает:
    рассинхрон флагов иначе дал бы схему кеглем наугад."""
    template, manifest, fonts = template_and_manifest(tmp_path)
    package = content()
    block = next(b for b in blocks(manifest) if b.block_id == "sa-hierarchy")
    assignment = RecipeAssignment(slide_id="s01", recipe_id=None, reason="примера нет")
    slide = fit_slide(slide_for(assignment, block, manifest), manifest, fonts=fonts,
                      content=package)
    deck = DeckIR(deck_id="d1", variant="A", template_id=manifest.template_id, seed=7,
                  slides=[slide])
    writer = PptxWriter(template, manifest, fonts=fonts, by_example=True)
    with pytest.raises(WriterError, match="s01/sa-hierarchy: нет замера вписывания"):
        writer.write(deck, tmp_path / "deck.pptx", package)


def test_html_shows_what_pptx_shows_on_the_by_example_path(tmp_path: Path) -> None:
    """HTML-экспорт деградирует и проверяет тем же путём сборки, что и pptx: иерархия слайда
    без примера остаётся схемой, а не превращается в список только в одном из форматов."""
    _, manifest, fonts = template_and_manifest(tmp_path)
    package = content()
    block = next(b for b in blocks(manifest) if b.block_id == "sa-hierarchy")
    assignment = RecipeAssignment(slide_id="s01", recipe_id=None, reason="примера нет")
    slide = fit_slide(slide_for(assignment, block, manifest), manifest, fonts=fonts,
                      content=package, by_example=True)
    deck = DeckIR(deck_id="d1", variant="A", template_id=manifest.template_id, seed=7,
                  slides=[slide])
    html = export_html(deck, manifest, tmp_path / "d.html", package, fonts,
                       by_example=True).read_text(encoding="utf-8")
    legacy = export_html(deck, manifest, tmp_path / "legacy.html", package,
                         fonts).read_text(encoding="utf-8")
    assert 'class="block smartart"' in html and 'class="block bullets"' not in html
    assert 'class="block bullets"' in legacy
