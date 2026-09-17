"""Проверки плотности: на нарушителе и на норме. Change (15)."""

from __future__ import annotations

from deckforge.audit.deterministic.density import (
    bullet_too_long,
    fill_ratio,
    table_too_big,
    too_many_bullets,
    too_many_series,
)
from deckforge.domain.content import Brief, ContentPackage, Dataset, Series
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import body, bullets, chart, context_for, deck, slide, table, title


def _content(series_count: int, *, unit: str | None = "млн ₽") -> ContentPackage:
    return ContentPackage(
        brief=Brief(purpose="report", audience="правление", target_slides=12),
        datasets=[
            Dataset(
                dataset_id="d001",
                title="Выручка по кварталам",
                categories=["Q1", "Q2", "Q3", "Q4"],
                series=[
                    Series(name=f"{2020 + index}", values=[1.0, 2.0, 3.0, 4.0])
                    for index in range(series_count)
                ],
                unit=unit,
            )
        ],
    )


def test_too_many_bullets_counts_the_whole_slide(manifest: TemplateManifest) -> None:
    """Семь пунктов, разложенные по двум блокам, остаются семью пунктами на слайде."""
    first = bullets("раз", "два", "три", "четыре", block_id="b2")
    second = bullets("пять", "шесть", "семь", block_id="b3", box=(3, 10, 8, 3))
    colony = deck(slide(title(), first, second))
    findings = list(too_many_bullets(context_for("density.too_many_bullets", colony, manifest)))
    assert [f.evidence["count"] for f in findings] == ["7"]


def test_too_many_bullets_silent_within_the_limit(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), bullets("раз", "два", "три")))
    assert list(too_many_bullets(context_for("density.too_many_bullets", colony, manifest))) == []


def test_bullet_too_long_catches_a_sentence(manifest: TemplateManifest) -> None:
    long_item = " ".join(["слово"] * 20)
    colony = deck(slide(bullets(long_item, "короткий")))
    findings = list(bullet_too_long(context_for("density.bullet_too_long", colony, manifest)))
    assert [f.evidence["words"] for f in findings] == ["20"]


def test_bullet_too_long_silent_on_short_items(manifest: TemplateManifest) -> None:
    colony = deck(slide(bullets("выручка выросла", "затраты снизились")))
    assert list(bullet_too_long(context_for("density.bullet_too_long", colony, manifest))) == []


def test_table_too_big_catches_a_document_sized_table(manifest: TemplateManifest) -> None:
    rows = [[f"строка {index}", "значение"] for index in range(9)]
    colony = deck(slide(table(rows=rows)))
    findings = list(table_too_big(context_for("density.table_too_big", colony, manifest)))
    assert [f.evidence["rows"] for f in findings] == ["10"]


def test_table_too_big_silent_on_a_readable_table(manifest: TemplateManifest) -> None:
    colony = deck(slide(table()))
    assert list(table_too_big(context_for("density.table_too_big", colony, manifest))) == []


def test_too_many_series_reads_the_dataset(manifest: TemplateManifest) -> None:
    colony = deck(slide(chart()))
    context = context_for(
        "density.too_many_series", colony, manifest, content=_content(series_count=6)
    )
    findings = list(too_many_series(context))
    assert [f.evidence["series"] for f in findings] == ["6"]


def test_too_many_series_silent_on_a_readable_chart(manifest: TemplateManifest) -> None:
    colony = deck(slide(chart()))
    context = context_for(
        "density.too_many_series", colony, manifest, content=_content(series_count=3)
    )
    assert list(too_many_series(context)) == []


def test_fill_ratio_catches_an_almost_empty_slide(manifest: TemplateManifest) -> None:
    colony = deck(slide(body("Одинокий тезис", box=(2, 2, 1, 1))))
    findings = list(fill_ratio(context_for("density.fill_ratio", colony, manifest)))
    assert "полупустой" in findings[0].message


def test_fill_ratio_silent_on_a_balanced_slide(manifest: TemplateManifest) -> None:
    colony = deck(slide(body("Содержательный блок", box=(2, 2, 24, 10))))
    assert list(fill_ratio(context_for("density.fill_ratio", colony, manifest))) == []


def test_fill_ratio_ignores_a_full_bleed_backdrop(manifest: TemplateManifest) -> None:
    """Фотография в край делает слайд «переполненным» только на бумаге, а не на деле."""
    backdrop = body("Подложка", block_id="b1", box=(0, 0, 35.4, 19))
    content_block = body("Тезис поверх", block_id="b2", box=(2, 2, 24, 10))
    colony = deck(slide(backdrop, content_block))
    assert list(fill_ratio(context_for("density.fill_ratio", colony, manifest))) == []
