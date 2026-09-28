"""Проверка гарнитур без файла колоды называет себя пропущенной, а не отдаёт тихий ноль.
Change `the-font-check-names-its-skip`, поток C, находка тимлида в #245.

Половина `template.font_not_in_theme` видна только в .pptx. Без файла она молча
пропускала эту половину и не попадала в `skipped_checks`: на переаудите фикстуры
Education 28.09 три гарнитуры, найденные прогоном по файлу, исчезли без следа.

Сценарии — из дельты `openspec/changes/the-font-check-names-its-skip/specs/`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deckforge.audit.deterministic.template import font_not_in_theme
from deckforge.audit.registry import CheckUnavailable
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline.replay import from_fixture, reaudit
from tests.unit._audit_builders import body, context_for, deck, slide, title

CHECK = "template.font_not_in_theme"
EDUCATION = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-28" / "education"


def test_without_the_file_a_clean_result_is_a_skip(manifest: TemplateManifest) -> None:
    """Нарушитель до правки: без файла проверка отдавала `[]` — «проверено, чисто»."""
    context = context_for(CHECK, deck(slide(title(), body())), manifest)

    with pytest.raises(CheckUnavailable):
        list(font_not_in_theme(context))


def test_without_the_file_a_finding_by_ir_still_counts(manifest: TemplateManifest) -> None:
    """Норма: находку по IR файл не отменяет — гарнитур больше порога уже по плейсхолдерам."""
    context = context_for(CHECK, deck(slide(title(), body())), manifest, max_families=1)

    findings = list(font_not_in_theme(context))

    assert [f for f in findings if f.evidence.get("families")]


def test_a_file_that_does_not_open_is_a_skip(manifest: TemplateManifest, tmp_path: Path) -> None:
    """Нарушитель до правки: битый файл читался как «гарнитур в файле нет»."""
    broken = tmp_path / "deck.pptx"
    broken.write_bytes(b"not a zip")
    context = context_for(CHECK, deck(slide(title(), body())), manifest, deck_path=broken)

    with pytest.raises(CheckUnavailable):
        list(font_not_in_theme(context))


def test_with_the_file_a_clean_deck_passes(manifest: TemplateManifest, tmp_path: Path) -> None:
    """Норма: файл есть и набран гарнитурой шаблона — проверка работает и молчит."""
    pptx = pytest.importorskip("pptx")
    path = tmp_path / "deck.pptx"
    presentation = pptx.Presentation()
    page = presentation.slides.add_slide(presentation.slide_layouts[5])
    run = page.shapes.title.text_frame.paragraphs[0].add_run()
    run.text = "Заголовок гарнитурой шаблона"
    run.font.name = manifest.theme.fonts.major_latin
    presentation.save(str(path))
    context = context_for(CHECK, deck(slide(title())), manifest, deck_path=path)

    assert list(font_not_in_theme(context)) == []


def test_the_reaudit_of_education_names_the_skip() -> None:
    """Переаудит фикстуры без .pptx: проверка названа в `skipped_checks`, а не «прошла»."""
    if not EDUCATION.is_dir():
        pytest.skip("нет фикстуры прогона Education 28.09")

    result = asyncio.run(reaudit(from_fixture(EDUCATION)))

    assert CHECK in result.skipped_checks
    assert CHECK not in {finding.check_id for finding in result.report.findings}
