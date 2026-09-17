"""Критерий change (17): колода собирается **одной командой**.

Инференс подделан — проверяется склейка транспорта: конфиг, варианты, бриф, обход
контент-пакета, каталоги артефактов и отчёт прогона.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from deckforge.cli import app
from deckforge.config import get_settings
from deckforge.parsing import TemplateParser
from tests.integration.test_native_objects import build_template
from tests.integration.test_pipeline_end_to_end import FakeInference

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv("DECKFORGE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    get_settings.cache_clear()

    template = build_template(tmp_path / "template.pptx")
    manifest = TemplateParser().parse(template, use_cache=False)

    fake = FakeInference(manifest)
    monkeypatch.setattr("deckforge.inference.factory.client_for", lambda *a, **k: fake)
    monkeypatch.setattr("deckforge.inference.factory.vlm_judge", lambda *a, **k: None)

    content = tmp_path / "content"
    content.mkdir()
    (content / "материалы.md").write_text(
        "Выручка выросла на 37,5 % за год.\n", encoding="utf-8"
    )
    brief = tmp_path / "brief.yaml"
    brief.write_text(
        "purpose: product\naudience: правление\ntarget_slides: 6\nlanguage: ru\n",
        encoding="utf-8",
    )
    config = tmp_path / "run.yaml"
    config.write_text(
        "seed: 1337\nvariants: [A, B]\nexports: [pptx, html]\n"
        "audit:\n  run_semantic: false\n  auto_fix: false\n",
        encoding="utf-8",
    )
    return {
        "template": template,
        "content": content,
        "brief": brief,
        "config": config,
        "out": tmp_path / "out",
    }


def invoke(project: dict[str, Path], *extra: str) -> Any:
    return runner.invoke(
        app,
        [
            "generate",
            str(project["template"]),
            str(project["content"]),
            "--brief",
            str(project["brief"]),
            "--config",
            str(project["config"]),
            "--out-dir",
            str(project["out"]),
            *extra,
        ],
    )


def test_one_command_produces_a_deck_and_a_run_report(project: dict[str, Path]) -> None:
    result = invoke(project)
    assert result.exit_code == 0, result.output

    out = project["out"] / "A"
    assert (out / "deck.pptx").is_file()
    assert (out / "deck.html").is_file()

    report = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert report["variant"] == "A" and report["seed"] == 1337
    assert report["slides"] > 0


def test_each_variant_lands_in_its_own_directory(project: dict[str, Path]) -> None:
    """Три варианта — требование C7: перезаписывать друг друга они не должны."""
    result = invoke(project, "--variant", "all")
    assert result.exit_code == 0, result.output
    assert (project["out"] / "A" / "deck.pptx").is_file()
    assert (project["out"] / "B" / "deck.pptx").is_file()


def test_unknown_variant_is_named_not_silently_skipped(project: dict[str, Path]) -> None:
    result = invoke(project, "--variant", "Z")
    assert result.exit_code != 0
    assert "Z" in str(result.exception)
