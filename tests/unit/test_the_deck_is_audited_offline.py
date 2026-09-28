"""Снимок прогона и переаудит без модели. Change `the-deck-is-audited-offline` (план Б, 6б).

До этого change любую правку перемеряли полным прогоном на стенде: 205–376 с и ключ
от стенда. Прогоны 28.09 теперь лежат фикстурами (`tests/fixtures/runs/2026-09-28/`):
план, IR, контент, манифест, дизайн-система и `run.json`. Потоки плана Б меряют по ним
свою правку за секунды — и эти тесты сторожат, что фикстуры читаются и переаудит честен.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from deckforge.cli import app
from deckforge.pipeline.replay import (
    CHECKPOINT_NAME,
    ReplayError,
    from_checkpoint,
    from_fixture,
    load_snapshot,
    reaudit,
    save_fixture,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "runs" / "2026-09-28"
#: Колода → (run_id, рецептов в каталоге, самый частый пример и сколько раз он стоит).
DECKS = {
    "workspace": ("c511fe7fa6e3", 29, 4),
    "vk-tech": ("7c44e7475db4", 54, 6),
    "education": ("3a93c140202f", 45, 4),
}


@pytest.mark.parametrize("name", sorted(DECKS))
def test_the_fixtures_of_28_09_read_as_models(name: str) -> None:
    """Норма: фикстура читается в модели домена целиком, план и колода — по 10 слайдов."""
    run_id, recipes, _ = DECKS[name]

    snapshot = from_fixture(FIXTURES / name)

    assert snapshot.run_id == run_id
    assert (len(snapshot.plan.slides), len(snapshot.deck.slides)) == (10, 10)
    assert len(snapshot.design_system.recipes) == recipes
    assert snapshot.manifest.template_id == snapshot.deck.template_id


def test_a_fixture_survives_its_own_round_trip(tmp_path: Path) -> None:
    """Норма: выгрузка и чтение не теряют ничего, а одинаковый снимок — одинаковые байты."""
    snapshot = from_fixture(FIXTURES / "vk-tech")

    first = [p.read_bytes() for p in save_fixture(snapshot, tmp_path / "one")]
    again = from_fixture(tmp_path / "one")
    second = [p.read_bytes() for p in save_fixture(again, tmp_path / "two")]

    assert again.deck == snapshot.deck and again.plan == snapshot.plan
    assert first == second


def test_the_reaudit_is_repeatable_and_names_what_it_did_not_measure() -> None:
    """Норма: переаудит без модели и превью даёт одно и то же и называет пропущенное."""
    snapshot = from_fixture(FIXTURES / "vk-tech")

    one = asyncio.run(reaudit(snapshot))
    two = asyncio.run(reaudit(snapshot))

    assert [f.finding_id for f in one.report.findings] == [
        f.finding_id for f in two.report.findings
    ]
    # Превью в фикстуре нет — проверка по картинкам обязана быть пропущенной, а не нулём.
    assert "design.ink_balance" in one.skipped_checks


def test_the_plan_b_baseline_is_reproduced_from_the_fixtures() -> None:
    """Норма: мерило плана Б по фикстурам даёт базу «до» — 0 из 24 и 4/6/4 повтора."""
    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        metrics = importlib.import_module("plan_b_metrics")
    finally:
        sys.path.remove(str(scripts))

    decks = {name: metrics.deck_metrics(metrics.load_report(FIXTURES / name)) for name in DECKS}

    assert sum(d.by_meaning for d in decks.values()) == 0
    assert sum(d.by_seats for d in decks.values()) == 24
    assert sum(d.content_slides for d in decks.values()) == 24
    assert {name: d.top_example_uses for name, d in decks.items()} == {
        name: uses for name, (_, _, uses) in DECKS.items()
    }


def test_a_run_dir_without_a_checkpoint_is_refused(tmp_path: Path) -> None:
    """Нарушитель: каталог без чекпойнта — названная ошибка, а не пустой снимок."""
    with pytest.raises(ReplayError, match=CHECKPOINT_NAME):
        from_checkpoint(tmp_path)


def test_an_empty_checkpoint_names_the_missing_thread(tmp_path: Path) -> None:
    """Нарушитель: чекпойнт без нити прогона — ошибка называет нить."""
    from deckforge.pipeline.run import open_checkpointer

    async def create() -> None:
        async with open_checkpointer(tmp_path / CHECKPOINT_NAME) as saver:
            await saver.setup()

    asyncio.run(create())

    with pytest.raises(ReplayError, match=f"{tmp_path.name}:A"):
        from_checkpoint(tmp_path)


def test_a_folder_without_a_fixture_is_refused(tmp_path: Path) -> None:
    """Нарушитель: ни чекпойнта, ни фикстуры — ошибка называет недостающий файл."""
    with pytest.raises(ReplayError, match=r"plan\.json\.gz"):
        load_snapshot(tmp_path)


def test_the_cli_audits_a_fixture(tmp_path: Path) -> None:
    """Норма: `deckforge audit <фикстура>` пишет отчёт и список пропущенных проверок."""
    out = tmp_path / "audit.json"

    result = CliRunner().invoke(app, ["audit", str(FIXTURES / "education"), "-o", str(out)])

    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["run_id"] == "3a93c140202f"
    assert "design.ink_balance" in payload["skipped_checks"]
