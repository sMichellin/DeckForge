"""Прогон аудита: воспроизводимость, пропуски, сводка. Change (15)."""

from __future__ import annotations

import pytest

from deckforge.audit import REGISTRY, AuditRunner
from deckforge.audit import deterministic as _deterministic  # регистрация проверок
from deckforge.audit import semantic as _semantic  # регистрация проверок
from deckforge.audit.semantic import spelling
from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import Severity
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import body, bullets, deck, slide, title

_ = (_deterministic, _semantic)


def _content() -> ContentPackage:
    return ContentPackage(brief=Brief(purpose="report", audience="правление", target_slides=12))


async def test_run_finds_violations_and_counts_them(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body("а" * 500, box=(30, 1, 10, 3))))
    report = await AuditRunner().run(colony, manifest, _content())

    assert report.deck_id == colony.deck_id
    assert report.has_errors
    ids = {finding.check_id for finding in report.findings}
    assert "layout.out_of_bounds" in ids
    assert report.summary.errors == len(report.of_severity(Severity.ERROR))


async def test_run_is_reproducible(manifest: TemplateManifest) -> None:
    """Два прогона на одной колоде дают один и тот же отчёт — иначе их не сравнить."""
    colony = deck(slide(title(), body("а" * 500)))
    first = await AuditRunner().run(colony, manifest, _content())
    second = await AuditRunner().run(colony, manifest, _content())

    assert [f.finding_id for f in first.findings] == [f.finding_id for f in second.findings]
    assert [f.check_id for f in first.findings] == [f.check_id for f in second.findings]


async def test_findings_are_sorted_by_slide_and_check(manifest: TemplateManifest) -> None:
    colony = deck(
        slide(title(), body("а" * 500), slide_id="s02"),
        slide(title(), body("б" * 500), slide_id="s01"),
    )
    report = await AuditRunner().run(colony, manifest, _content())
    keys = [(f.slide_id or "", f.check_id, f.finding_id) for f in report.findings]
    assert keys == sorted(keys)


async def test_unavailable_checks_are_skipped_not_passed(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Проверке нечего смотреть — она попадает в пропущенные, а не в пройденные.

    Без готового файла нечего открывать (`integrity.file_opens`) и негде увидеть
    растяжение картинки; без LanguageTool нечем проверить орфографию; без направляющих
    не с чем сверять выравнивание. «Не запускалась» и «прошла» — разные состояния.
    """
    monkeypatch.setattr(spelling, "checker_factory", lambda language, url: None)
    colony = deck(slide(title(), bullets("первое", "второе")))
    runner = AuditRunner()
    await runner.run(colony, manifest, _content())

    assert "content.no_typos" in runner.skipped_checks
    assert "integrity.file_opens" in runner.skipped_checks
    assert "layout.image_aspect_distorted" in runner.skipped_checks
    assert "layout.off_guides" in runner.skipped_checks


async def test_enabled_checks_narrow_the_run(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body("а" * 500, box=(30, 1, 10, 3))))
    runner = AuditRunner(enabled_checks=["layout.out_of_bounds"])
    report = await runner.run(colony, manifest, _content())

    assert {f.check_id for f in report.findings} == {"layout.out_of_bounds"}
    assert "layout.overlap" in runner.skipped_checks


async def test_clean_deck_produces_no_errors(manifest: TemplateManifest) -> None:
    """Аккуратно собранный слайд не должен давать ошибок — иначе отчёту перестают верить."""
    colony = deck(slide(title("Выручка выросла на треть"), bullets("первое", "второе")))
    report = await AuditRunner().run(colony, manifest, _content())
    assert report.of_severity(Severity.ERROR) == []


def test_deterministic_checks_cover_three_content_questions() -> None:
    """Тридцать три детерминированные проверки: 30 в `deterministic/` и три из `semantic/`.

    Папка отвечает на вопрос «про смысл ли проверка», а флаг `deterministic` —
    «одинаков ли результат на повторных запусках». Три вопроса Приложения 1 уведены
    из модели в код (change 18): опечатки — LanguageTool, числа — сверка с контент-пакетом,
    язык — подсчёт букв. Каждый уведённый вопрос экономит 12 вызовов VLM на колоду.
    """
    deterministic = {c.check_id for c in REGISTRY.deterministic()}
    assert len(deterministic) == 34
    assert {"content.no_typos", "content.numbers_grounded", "content.single_language"} <= (
        deterministic
    )


def test_runner_populates_the_registry_itself() -> None:
    """Проверки заводятся импортом своего модуля, и прогон обязан это обеспечить сам.

    Потребитель, импортировавший только `AuditRunner` (узел графа change 17), получал
    пустой реестр — ноль находок, ноль пройденных, ноль пропущенных. Отчёт при этом
    неотличим от чистой колоды: «аудит прошёл, нарушений нет».
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    import deckforge

    # Подпроцесс не видит `pythonpath` из pytest: без установленного пакета (локально,
    # не через poetry) он падал на `import deckforge`, а не на пустом реестре.
    src = str(Path(deckforge.__file__).resolve().parents[1])
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, [src, os.environ.get("PYTHONPATH")])),
    }
    probe = (
        "from deckforge.audit.runner import AuditRunner;"
        "from deckforge.audit.registry import REGISTRY;"
        "print(len(REGISTRY))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, env=env
    )
    assert int(out.stdout.strip()) > 0, "импорта прогона не хватило, чтобы завести проверки"
