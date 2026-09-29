"""Колода заново без модели. Change `the-deck-is-rebuilt-without-a-model` (план Б, тимлид).

Живой прогон — 2–3 минуты и очередь к единственному слоту модели. Правке вёрстки, писателя,
экспорта и аудита модель не нужна: план и текст слайдов уже лежат в чекпойнте прогона.
Пересборка ответвляется от точки перед `fit` и гонит остальное текущим кодом.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deckforge.config import RunConfig
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.replay import CHECKPOINT_NAME, ReplayError, from_checkpoint, rebuild
from deckforge.pipeline.run import load_brief
from tests.integration.test_pipeline_end_to_end import run_pipeline, workspace

__all__ = ["workspace"]


def _no_model_deps(workspace: dict[str, Path], out: Path, fonts: object) -> Deps:
    return Deps(
        brief=load_brief(workspace["brief"]),
        run=RunConfig(exports=["pptx"], audit={"run_semantic": False, "auto_fix": False}),
        out_dir=out / "out",
        fonts=fonts,  # type: ignore[arg-type]
        cache_dir=workspace["root"] / "cache",
        work_dir=out / "out",
    )


@pytest.fixture
async def finished_run(workspace: dict[str, Path]) -> tuple[Path, object]:
    """Прогон на поддельной модели с чекпойнтом — как его кладёт стенд."""
    run_dir = workspace["root"] / "runs" / "run1"
    result, deps = await run_pipeline(workspace, checkpoint_path=run_dir / CHECKPOINT_NAME)
    assert not result.interrupted
    result.write_report()
    return run_dir, deps.fonts


def test_the_deck_is_rebuilt_without_a_model(
    workspace: dict[str, Path], finished_run: tuple[Path, object], tmp_path: Path
) -> None:
    """Норма: без модели (`llm` и `vlm` пусты) из чекпойнта выходит колода и отчёт прогона,
    текст слайдов — тот же, что написала модель в исходном прогоне."""
    run_dir, fonts = finished_run
    out = tmp_path / "rebuilt"

    result = rebuild(run_dir, out, _no_model_deps(workspace, out, fonts))

    assert (out / "out" / "deck.pptx").is_file()
    report = json.loads((out / "out" / "run.json").read_text(encoding="utf-8"))
    assert report["run_id"] == result.run_id

    def texts(run: Path) -> list[list[str | None]]:
        deck = from_checkpoint(run).deck
        return [[getattr(block, "text", None) for block in slide.blocks] for slide in deck.slides]

    assert texts(out) == texts(run_dir) != []


def test_the_source_run_is_left_untouched(
    workspace: dict[str, Path], finished_run: tuple[Path, object], tmp_path: Path
) -> None:
    """Норма: чекпойнт исходного прогона не меняется — пересборка пишет в свою копию."""
    run_dir, fonts = finished_run
    source = run_dir / CHECKPOINT_NAME
    before = source.read_bytes()

    rebuild(run_dir, tmp_path / "r", _no_model_deps(workspace, tmp_path / "r", fonts))

    assert source.read_bytes() == before


def test_a_run_dir_without_a_checkpoint_is_refused(tmp_path: Path) -> None:
    """Нарушитель: пересобирать не из чего — названная ошибка, а не пустая колода."""
    with pytest.raises(ReplayError, match=CHECKPOINT_NAME):
        rebuild(tmp_path, tmp_path / "out", None)

