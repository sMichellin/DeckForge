"""Приёмочный контент-пакет несёт всё, что колода должна уметь показать. Т6
(`docs/agents/requirements-from-notes-26-09.md`), change `acceptance-content-pack`.

Прогоны шли на тексте без данных: у колод был пустой словарь дизайн-системы, и ни
диаграммы, ни таблицы, ни показателей проверить было не на чем. Тест сторожит состав
пакета `tests/fixtures/content/acceptance`: если его «упростят», прогоны приёмки молча
перестанут проверять половину колоды.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deckforge.domain.content import Brief, ContentPackage
from deckforge.parsing.content import ContentIngestor
from deckforge.pipeline.run import collect_content_paths

PACK = Path(__file__).resolve().parents[1] / "fixtures" / "content" / "acceptance"


@pytest.fixture(scope="module")
def package() -> ContentPackage:
    brief = Brief.model_validate(yaml.safe_load((PACK / "brief.yaml").read_text(encoding="utf-8")))
    return ContentIngestor().ingest(collect_content_paths(PACK), brief)


def test_the_pack_has_a_series_for_a_chart(package: ContentPackage) -> None:
    """Ряды по категориям с единицей — материал для диаграммы."""
    charts = [d for d in package.datasets if len(d.series) >= 2 and d.unit]
    assert charts, [d.title for d in package.datasets]
    chart = charts[0]
    assert len(chart.categories) >= 4
    assert all(value is not None for series in chart.series for value in series.values)


def test_the_pack_has_a_table(package: ContentPackage) -> None:
    """Таблица 5–7 строк и 3–5 столбцов — в пределах ТЗ (не больше 7 × 5)."""
    tables = [
        d for d in package.datasets if 5 <= len(d.categories) <= 7 and 3 <= len(d.series) <= 5
    ]
    assert tables, [(len(d.categories), len(d.series)) for d in package.datasets]


def test_the_pack_has_big_numbers(package: ContentPackage) -> None:
    """Не меньше четырёх фактов с числами — материал для KPI."""
    assert sum(1 for fact in package.facts if fact.numbers) >= 4


def test_the_pack_has_a_quote_with_an_author(package: ContentPackage) -> None:
    quotes = [f for f in package.facts if "«" in f.text and "»," in f.text and "—" in f.text]
    assert quotes, "цитаты с автором нет"


def test_the_pack_has_a_process_written_with_arrows(package: ContentPackage) -> None:
    assert any(fact.text.count("→") >= 2 for fact in package.facts)


def test_the_pack_has_a_list_of_homogeneous_points() -> None:
    text = (PACK / "content.md").read_text(encoding="utf-8")
    points = [line for line in text.splitlines() if line.startswith("- ")]
    assert 3 <= len(points) <= 6


def test_no_service_text_leaks_into_the_facts(package: ContentPackage) -> None:
    """Пояснения о самом пакете живут в README: из `content.md` они ушли бы на слайд."""
    assert not [f.text for f in package.facts if "приёмк" in f.text or "вымышл" in f.text]
