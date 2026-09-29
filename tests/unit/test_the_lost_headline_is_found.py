"""Слайд с заголовком без слов и без содержания — содержание потеряно. Change
`the-lost-headline-is-found`, план Б, круг 2 (строка мерила 9), поток C, #245.

Обложка WorkSpace 29.09 вышла с «1» вместо заголовка плана и без единого блока. Фактов план
ей не давал, поэтому `integrity.content_lost` её пропускал, а `integrity.empty_slide` —
тоже: у макета обложки нет места под тело. Строка 9 насчитывала два слайда из трёх.

Сценарии — из дельты `openspec/changes/the-lost-headline-is-found/specs/audit-deterministic/`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deckforge.audit.deterministic.integrity import content_lost
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import Provenance, SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline.replay import from_fixture, reaudit
from tests.unit._audit_builders import context_for, deck

CHECK = "integrity.content_lost"
RUNS = Path(__file__).resolve().parents[1] / "fixtures" / "runs"


def cover(*texts: str, facts: list[str] | None = None) -> SlideIR:
    """Слайд: первый текст — заголовок, остальные — тело."""
    blocks = [TextBlock(block_id="b01", role=TextRole.TITLE, text=texts[0])]
    blocks += [
        TextBlock(block_id=f"b{n:02d}", role=TextRole.BODY, text=text)
        for n, text in enumerate(texts[1:], start=2)
    ]
    return SlideIR(slide_id="s01", layout_id="L01", variant="A", blocks=blocks,
                   provenance=Provenance(fact_refs=facts or []))


def found(manifest: TemplateManifest, slide: SlideIR) -> list:
    return list(content_lost(context_for(CHECK, deck(slide), manifest)))


def test_a_cover_with_a_number_instead_of_the_headline_lost_its_content(
    manifest: TemplateManifest,
) -> None:
    """Нарушитель (WorkSpace 29.09 s01): «1» вместо заголовка, больше ничего, фактов не было."""
    findings = found(manifest, cover("1"))

    assert [(f.slide_id, f.evidence["title"]) for f in findings] == [("s01", "1")]


def test_a_cover_with_a_worded_headline_is_whole(manifest: TemplateManifest) -> None:
    """Норма: обложка из одного заголовка словами — композиция по замыслу."""
    assert found(manifest, cover("Автоматизация создания презентаций")) == []


def test_a_wordless_headline_over_a_body_is_not_this_finding(manifest: TemplateManifest) -> None:
    """Норма: заголовок «1», но факты на слайде есть (WorkSpace s04) — содержание не потеряно;
    заголовок-число — корень К2, а не строка 9."""
    assert found(manifest, cover("1", "Шаблон разбирается за минуты")) == []


def test_facts_dropped_is_still_found(manifest: TemplateManifest) -> None:
    """Прежнее правило цело: заголовок словами, факты были, тела нет."""
    findings = found(manifest, cover("Итоги квартала", facts=["f001", "f002"]))

    assert [f.evidence.get("fact_refs") for f in findings] == ["f001, f002"]


@pytest.mark.parametrize("title", ["10x", "2024", "— 1 —", "№ 3"])
def test_numbers_and_signs_are_not_words(manifest: TemplateManifest, title: str) -> None:
    assert len(found(manifest, cover(title))) == 1


def _row_9(day: str, name: str) -> set[str]:
    folder = RUNS / day / name
    if not folder.is_dir():
        pytest.skip(f"нет фикстуры {day}/{name}")
    report = asyncio.run(reaudit(from_fixture(folder))).report
    return {
        f.slide_id or ""
        for f in report.findings
        if f.check_id in ("integrity.content_lost", "integrity.empty_slide")
    }


def test_row_9_of_29_09_counts_the_three_slides() -> None:
    """Мерило: потерянные факты 29.09 — WorkSpace s01, s10 и Education s10, как видно глазами."""
    assert _row_9("2026-09-29", "workspace") == {"s01", "s10"}
    assert _row_9("2026-09-29", "vk-tech") == set()
    assert _row_9("2026-09-29", "education") == {"s10"}
