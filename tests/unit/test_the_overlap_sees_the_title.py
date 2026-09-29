"""Проверка наложения видит заголовок. Change `the-overlap-sees-the-title`, план Б, круг 2
(`docs/agents/tasks-plan-b-round-2.md`, К5), поток C, #245.

Education 29.09 s02, s08: решатель положил выноску и схему над заголовком, их текст не влез
и упёрся в заголовок. Рамки только касались, пересечение по тексту — четыре процента
площади меньшего блока, ниже порога 5 %, и `layout.overlap` молчал. Правило 7: нарушитель
и норма.

Сценарии — из дельты `openspec/changes/the-overlap-sees-the-title/specs/audit-deterministic/`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deckforge.audit.deterministic.layout import overlap
from deckforge.domain.enums import CalloutTone, TextRole
from deckforge.domain.slide import CalloutBlock, FitResult, SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline.replay import from_fixture, reaudit
from tests.unit._audit_builders import context_for, deck

CHECK = "layout.overlap"
RUNS = Path(__file__).resolve().parents[1] / "fixtures" / "runs"


def _title_box(manifest: TemplateManifest) -> tuple[int, int, int, int]:
    """Рамка заголовка первого макета с плейсхолдером заголовка idx=0."""
    for layout in manifest.layouts:
        for placeholder in layout.placeholders:
            if placeholder.idx == 0 and placeholder.role is TextRole.TITLE:
                box = placeholder.bbox
                return box.x, box.y, box.cx, box.cy
    pytest.skip("у тестового шаблона нет заголовка idx=0")


def _layout_id(manifest: TemplateManifest) -> str:
    return next(
        layout.layout_id for layout in manifest.layouts
        if any(p.idx == 0 and p.role is TextRole.TITLE for p in layout.placeholders)
    )


def run(manifest: TemplateManifest, *, y: int, cy: int, required: int | None = None) -> list:
    """Заголовок в плейсхолдере и выноска с координатами `y`, `cy`; `required` — замер текста."""
    x, _, cx, _ = _title_box(manifest)
    callout = CalloutBlock(block_id="b2", text="Ручная адаптация шаблонов занимает часы",
                           tone=CalloutTone.INSIGHT, x=x, y=y, cx=cx, cy=cy)
    fit = {}
    if required is not None:
        fit["b2"] = FitResult(final_size_pt=18, overflow=required > cy, required_cy_emu=required)
    slide = SlideIR(
        slide_id="s02", layout_id=_layout_id(manifest), variant="A", fit_report=fit,
        blocks=[TextBlock(block_id="b0", placeholder_idx=0, role=TextRole.TITLE,
                          text="Без дизайнера слайды не собрать"), callout],
    )
    return [f for f in overlap(context_for(CHECK, deck(slide), manifest))
            if f.evidence.get("title_block_id")]


def test_a_callout_whose_text_hits_the_title_is_a_finding(manifest: TemplateManifest) -> None:
    """Нарушитель (Education s02): рамка кончается на верхнем крае заголовка, а не влезший
    текст выходит ниже — в заголовок."""
    _, title_y, _, _ = _title_box(manifest)
    height = title_y // 2

    findings = run(manifest, y=title_y - height, cy=height, required=height + height // 10)

    assert [(f.block_id, f.evidence["kind"]) for f in findings] == [("b2", "touches")]


def test_a_block_above_the_title_is_a_finding(manifest: TemplateManifest) -> None:
    """Нарушитель: блок влез, но стоит в полосе над заголовком — это место заголовка."""
    _, title_y, _, _ = _title_box(manifest)
    height = title_y // 2

    findings = run(manifest, y=title_y - height - 10, cy=height, required=height // 2)

    assert [(f.block_id, f.evidence["kind"]) for f in findings] == [("b2", "above")]


def test_a_callout_below_the_title_is_not_a_finding(manifest: TemplateManifest) -> None:
    """Норма: выноска под заголовком и текст её влез."""
    _, title_y, _, title_cy = _title_box(manifest)

    assert run(manifest, y=title_y + title_cy + 10, cy=title_cy, required=title_cy // 2) == []


def test_a_frame_overlap_is_reported_once(manifest: TemplateManifest) -> None:
    """Рамки легли друг на друга больше порога — это общая часть проверки, без дубля."""
    _, title_y, _, title_cy = _title_box(manifest)

    assert run(manifest, y=title_y, cy=title_cy) == []


def _overlaps(day: str, name: str) -> set[tuple[str, str]]:
    folder = RUNS / day / name
    if not folder.is_dir():
        pytest.skip(f"нет фикстуры {day}/{name}")
    report = asyncio.run(reaudit(from_fixture(folder))).report
    return {(f.slide_id or "", f.block_id or "") for f in report.findings if f.check_id == CHECK}


def test_education_29_09_s02_and_s08_are_found() -> None:
    """Мерило: наезд выноски и схемы на заголовок Education 29.09 — ровно два слайда."""
    assert _overlaps("2026-09-29", "education") == {("s02", "b2"), ("s08", "b2")}


@pytest.mark.parametrize(("day", "name"), [
    ("2026-09-29", "workspace"), ("2026-09-29", "vk-tech"),
    ("2026-09-28", "workspace"), ("2026-09-28", "vk-tech"), ("2026-09-28", "education"),
])
def test_other_decks_stay_clean(day: str, name: str) -> None:
    """Норма: на остальных колодах обоих дней заголовок никто не задевает."""
    assert _overlaps(day, name) == set()
