"""Разбор контент-пакета. Change (7) `content-ingestion`.

Проверяется то, что сломалось на живом прогоне (proposal.md, раздел Explore):
рваные абзацы PDF, пустая шапка таблицы `.docx`, `2025.0` и `NaN` из Excel.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from deckforge.domain.content import Brief
from deckforge.parsing.content import (
    ContentIngestionError,
    ContentIngestor,
    _dataset_from_rows,
    _normalize,
)

SYNTHETIC = Path(__file__).resolve().parents[1] / "fixtures" / "content" / "synthetic"

NBSP = " "


@pytest.fixture
def brief() -> Brief:
    return Brief(purpose="product", audience="правление", target_slides=12, language="ru")


def has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


# --------------------------------------------------------------------- нормализация


def test_broken_pdf_paragraph_is_joined() -> None:
    """PDF отдаёт заголовок по одному слову на абзац — до разбора это склеивается."""
    raw = "Аналитическая\n\n записка:\n\n рынок\n\nуправления\n\nОбъём рынка — 48,3 млрд ₽.\n"
    assert _normalize(raw).split("\n")[0] == "Аналитическая записка: рынок управления"


def test_double_spaces_collapse_but_nbsp_survives() -> None:
    """Двойные пробелы — артефакт PDF. Неразрывный пробел — часть записи числа."""
    assert _normalize("доля  68  %") == "доля 68 %"
    money = f"выручка 1{NBSP}200{NBSP}млн{NBSP}₽"
    assert _normalize(money) == money


def test_structure_is_not_glued_together() -> None:
    raw = "# Итоги\n* Выручка выросла\n* Отток снизился\n| a | b |\n"
    assert _normalize(raw).split("\n") == [
        "# Итоги",
        "* Выручка выросла",
        "* Отток снизился",
        "| a | b |",
    ]


# ------------------------------------------------------------------------ датасеты


def test_header_is_found_even_when_the_first_row_is_empty() -> None:
    """Ровно то, что markitdown делает с таблицей из .docx."""
    rows = [
        ["", "", ""],
        ["Квартал", "2025", "2026"],
        ["Q1", "180", "241"],
        ["Q2", "204", "287"],
    ]
    dataset = _dataset_from_rows(rows, "d001", "таблица", "документ.docx")
    assert dataset is not None
    assert dataset.categories == ["Q1", "Q2"]
    assert [series.name for series in dataset.series] == ["2025", "2026"]


def test_sheet_title_becomes_dataset_title_and_unit() -> None:
    rows = [
        ["Выручка по кварталам, млн ₽", None, None],
        [None, None, None],
        ["Квартал", 2025.0, 2026.0],
        ["Q1", 180.0, 241.0],
        ["Q2", 204.0, 287.0],
        ["Итого", 872.0, 1200.0],
    ]
    dataset = _dataset_from_rows(rows, "d001", "Лист1", "метрики.xlsx#Лист1")
    assert dataset is not None
    assert dataset.title == "Выручка по кварталам, млн ₽"
    assert dataset.unit == "млн ₽"
    names = [series.name for series in dataset.series]
    assert names == ["2025", "2026"], "«2025.0» в шапке датасета — враньё"
    assert "Итого" not in dataset.categories, "итоговая строка на диаграмме искажает картину"


def test_garbage_sheet_yields_nothing() -> None:
    rows = [[None, None], [None, None], [None, "черновик, не использовать"]]
    assert _dataset_from_rows(rows, "d001", "Лист3", "метрики.xlsx#Лист3") is None


# --------------------------------------------------------------------------- факты


def test_every_number_gets_a_fact_id(tmp_path: Path, brief: Brief) -> None:
    """Критерий выхода change (7): без этого аудит не сможет сверить цифры с источником."""
    source = tmp_path / "content.md"
    source.write_text(
        "# Итоги\n"
        f"Выручка выросла на 37,5{NBSP}% и достигла 1{NBSP}200{NBSP}млн{NBSP}₽.\n"
        "Клиентов стало более 500 против 320 годом ранее.\n",
        encoding="utf-8",
    )
    package = ContentIngestor().ingest([source], brief)

    assert package.facts, "факты не извлеклись"
    assert all(fact.fact_id.startswith("f") for fact in package.facts)
    assert len({fact.fact_id for fact in package.facts}) == len(package.facts)
    assert package.all_numbers, "числа потерялись"
    for fact in package.facts:
        for number in fact.numbers:
            assert package.fact(fact.fact_id) is not None
            assert number.raw, "исходное написание обязано сохраняться"


def test_source_ref_points_at_a_line(tmp_path: Path, brief: Brief) -> None:
    source = tmp_path / "заметка.md"
    source.write_text(
        "Первая строка про рост.\nВторая строка про 37,5 % роста.\n", encoding="utf-8"
    )
    package = ContentIngestor().ingest([source], brief)
    refs = {fact.source_ref for fact in package.facts}
    assert refs == {"заметка.md#L1", "заметка.md#L2"}


def test_ingestion_is_reproducible(tmp_path: Path, brief: Brief) -> None:
    """C11: повторный запуск обязан дать те же идентификаторы."""
    first = tmp_path / "b.md"
    second = tmp_path / "a.md"
    first.write_text("Выручка выросла на 12 %.\n", encoding="utf-8")
    second.write_text("Отток снизился на 3 п.п.\n", encoding="utf-8")
    ingestor = ContentIngestor()
    one = ingestor.ingest([first, second], brief)
    two = ingestor.ingest([second, first], brief)
    assert [fact.text for fact in one.facts] == [fact.text for fact in two.facts]


# --------------------------------------------------------------------------- отказы


def test_unknown_format_is_refused_with_a_hint(tmp_path: Path, brief: Brief) -> None:
    source = tmp_path / "архив.zip"
    source.write_bytes(b"PK\x03\x04")
    with pytest.raises(ContentIngestionError, match="не поддерживается"):
        ContentIngestor().ingest([source], brief)


def test_missing_file_is_refused(tmp_path: Path, brief: Brief) -> None:
    with pytest.raises(ContentIngestionError, match="файла нет"):
        ContentIngestor().ingest([tmp_path / "нет.md"], brief)


# ------------------------------------------------------ живой пакет, если есть чем


needs_converters = pytest.mark.skipif(
    not (SYNTHETIC.exists() and has("openpyxl")),
    reason="нужны синтетический пакет и openpyxl",
)


def test_every_pack_has_a_valid_brief() -> None:
    """Пять пакетов — пять назначений ТЗ: фича, продукт, проект, инициатива, отчёт."""
    import yaml

    packs = sorted(path for path in SYNTHETIC.iterdir() if path.is_dir())
    purposes = set()
    for pack in packs:
        raw = yaml.safe_load((pack / "brief.yaml").read_text(encoding="utf-8"))
        purposes.add(Brief(**raw).purpose)
    assert purposes == {"feature", "product", "project", "initiative", "report"}


@needs_converters
def test_synthetic_workbook_gives_clean_datasets(brief: Brief) -> None:
    package = ContentIngestor().ingest([SYNTHETIC / "product" / "Метрики_платформы.xlsx"], brief)
    assert len(package.datasets) == 2, "мусорный лист обязан отброситься"
    revenue = package.datasets[0]
    assert revenue.categories == ["Q1", "Q2", "Q3", "Q4"]
    assert [series.name for series in revenue.series] == ["2025", "2026"]
    assert revenue.series[1].values == [241.0, 287.0, 312.0, 360.0]


@pytest.mark.skipif(not (SYNTHETIC.exists() and has("mammoth")), reason="нужен конвертер .docx")
def test_real_docx_table_recovers_its_header(brief: Brief) -> None:
    """Живая проверка находки из Explore: markitdown отдаёт шапку таблицы пустой строкой."""
    source = SYNTHETIC / "product" / "Орбита_описание_продукта.docx"
    package = ContentIngestor().ingest([source], brief)

    assert package.facts, "из .docx не извлеклось ни одного факта"
    assert package.datasets, "таблица выручки не стала датасетом"
    revenue = package.datasets[0]
    assert revenue.categories == ["Q1", "Q2", "Q3", "Q4"]
    assert [series.name for series in revenue.series] == ["2025", "2026"]

    raws = {number.raw for number in package.all_numbers}
    assert any("1" in raw and "200" in raw for raw in raws), "неразрывный пробел сломал число"


@pytest.mark.skipif(not (SYNTHETIC.exists() and has("pdfminer")), reason="нужен конвертер .pdf")
def test_real_pdf_survives_broken_paragraphs(brief: Brief) -> None:
    """PDF рвёт абзацы по слову. Факт из одного слова — признак, что склейка не сработала."""
    source = SYNTHETIC / "report" / "разбор_инцидента.pdf"
    package = ContentIngestor().ingest([source], brief)

    assert package.facts, "из .pdf не извлеклось ни одного факта"
    assert all(len(fact.text.split()) >= 3 for fact in package.facts)
    assert any(len(fact.text.split()) >= 10 for fact in package.facts), "абзацы остались рваными"


def test_incident_timeline_keeps_durations_and_drops_clock_time(brief: Brief) -> None:
    """Хронология инцидента: «14:32» — не факт, «35 минут» — факт."""
    source = SYNTHETIC / "report" / "хронология.md"
    if not source.exists():
        pytest.skip("нет синтетического пакета отчёта")
    package = ContentIngestor().ingest([source], brief)

    values = {number.value for number in package.all_numbers}
    assert 35.0 in values, "длительность простоя потерялась"
    assert 66.0 in values, "доля затронутых клиентов потерялась"
    assert 32.0 not in values, "минуты из «14:32» попали в факты как отдельное число"
    assert 41.0 not in values, "минуты из «14:41» попали в факты как отдельное число"


def test_converter_failure_names_the_missing_dependency(tmp_path: Path, brief: Brief) -> None:
    """Базовая сборка markitdown не читает .docx. Отказ обязан называть причину.

    Без этого сообщения пользователь видит внутреннюю ошибку библиотеки и не понимает,
    что дело в сборке образа, а не в его файле.
    """
    broken = tmp_path / "договор.docx"
    broken.write_bytes("не настоящий docx".encode())
    with pytest.raises(ContentIngestionError, match="markitdown"):
        ContentIngestor().ingest([broken], brief)
