"""Дизайн-система лежит в папке прогона. Change `design-system-in-the-run-folder`, Т2
(`docs/agents/requirements-from-notes-26-09.md`).

Заметка 26.09: «Нет отдельного файла с дизайн-системой в папке, чтобы проверить».
Страница собиралась только командой `deckforge design-system`; узел `export` её не писал.

Сценарии — из дельты `openspec/changes/design-system-in-the-run-folder/specs/`.
Шаблон — стандартный шаблон python-pptx (C6).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deckforge.config import RunConfig
from deckforge.designsystem import DesignSystem, derive
from deckforge.export.design_system_page import render
from deckforge.parsing import TemplateParser
from deckforge.pipeline import nodes
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.run import RunResult, collect_content_paths, generate_variant, load_brief
from deckforge.registry import load_variant_profiles
from tests.integration.test_native_objects import build_template
from tests.integration.test_pipeline_end_to_end import FakeInference, theme_fonts


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    content = tmp_path / "content"
    content.mkdir()
    (content / "факты.md").write_text(
        "# Итоги года\n\nВыручка выросла на 37,5 % за год.\n\nКлиентов стало более 500.\n",
        encoding="utf-8",
    )
    brief = tmp_path / "brief.yaml"
    brief.write_text(
        "purpose: product\naudience: правление\ntarget_slides: 6\nlanguage: ru\n",
        encoding="utf-8",
    )
    return {
        "template": build_template(tmp_path / "template.pptx"),
        "content": content,
        "brief": brief,
        "root": tmp_path,
    }


async def run(workspace: dict[str, Path]) -> RunResult:
    root = workspace["root"]
    manifest = TemplateParser(cache_dir=root / "cache").parse(workspace["template"])
    out_dir = root / "out"
    deps = Deps(
        brief=load_brief(workspace["brief"]),
        run=RunConfig(exports=["pptx"], audit={"run_semantic": False, "auto_fix": False}),
        out_dir=out_dir,
        llm=FakeInference(manifest),
        fonts=theme_fonts(root, manifest),
        cache_dir=root / "cache",
        work_dir=out_dir,
    )
    return await generate_variant(
        workspace["template"],
        collect_content_paths(workspace["content"]),
        load_variant_profiles()["A"],
        deps,
        seed=1337,
        run_id="ds-files",
    )


async def test_the_run_folder_has_the_design_system(workspace: dict[str, Path]) -> None:
    """Нарушитель до правки: в папке прогона только колода."""
    result = await run(workspace)
    out = workspace["root"] / "out"

    assert (out / "design-system.html").is_file()
    assert (out / "design-system.json").is_file()

    report = json.loads(result.write_report().read_text(encoding="utf-8"))
    assert report["design_system_files"] == {
        "html": str(out / "design-system.html"),
        "json": str(out / "design-system.json"),
    }


async def test_the_page_is_the_page_of_the_command(workspace: dict[str, Path]) -> None:
    """Команда `design-system` = `render(derive(разбор шаблона))` — страница та же."""
    await run(workspace)
    page = (workspace["root"] / "out" / "design-system.html").read_text(encoding="utf-8")

    manifest = TemplateParser().parse(workspace["template"], use_cache=False)
    assert page == render(derive(manifest))


async def test_the_json_reads_back_as_the_deck_design_system(
    workspace: dict[str, Path],
) -> None:
    result = await run(workspace)
    raw = (workspace["root"] / "out" / "design-system.json").read_text(encoding="utf-8")

    assert DesignSystem.model_validate_json(raw) == result.state["design_system"]


async def test_a_failing_page_does_not_take_the_deck(
    workspace: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(ds: DesignSystem) -> str:
        raise RuntimeError("страница не собралась")

    monkeypatch.setattr(nodes.export, "render_design_system", broken)
    result = await run(workspace)

    assert result.exports["pptx"].is_file(), "колода ушла вместе со страницей"
    assert any(
        "дизайн-система не записана" in error and "RuntimeError" in error
        for error in result.state["errors"]
    )
    assert result.state.get("design_system_files") == {}
