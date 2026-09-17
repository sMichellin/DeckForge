"""Сквозной прогон графа. Change (17) `pipeline-orchestration`.

Модель подделана: проверяется не качество колоды, а то, что все слои соединены —
из шаблона и контент-пакета одной командой получаются файлы, отчёт прогона и аудит,
а всё, что не отработало, названо.

Шаблон — стандартный шаблон самой python-pptx: валидный пакет, не принадлежащий
организаторам и не похожий на их шаблоны (C6).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deckforge.config import RunConfig
from deckforge.domain.content import Brief
from deckforge.domain.enums import LayoutKind, TextRole
from deckforge.domain.template import TemplateManifest
from deckforge.inference.client import Completion
from deckforge.layout.fonts import FontLibrary
from deckforge.parsing import TemplateParser
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.run import (
    RunResult,
    collect_content_paths,
    generate_variant,
    load_brief,
)
from deckforge.registry import load_variant_profiles
from tests.integration.test_native_objects import build_template
from tests.unit.test_layout_fonts import make_font

SLIDES_IN_PLAN = 6


class FakeInference:
    """Один клиент на обе стадии: план и слайд различаются по имени схемы.

    `generate_model` передаёт `schema_name=<имя доменной модели>` — этого хватает,
    чтобы подделка не гадала по тексту промпта.
    """

    model = "fake"

    def __init__(self, manifest: TemplateManifest) -> None:
        self.manifest = manifest
        self.calls: list[str] = []

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Completion:
        name = str(kwargs.get("schema_name", ""))
        self.calls.append(name)
        payload = self._plan() if name == "DeckPlan" else self._slide()
        return Completion(text=json.dumps(payload, ensure_ascii=False), model=self.model)

    def _plan(self) -> dict[str, Any]:
        intents = ["title", "problem", "solution", "evidence", "summary", "closing"]
        return {
            "deck_id": "d1",
            "variant": "A",
            "seed": 1337,
            "language": "ru",
            "slides": [
                {
                    "slide_id": f"s{i:02d}",
                    "intent": intent,
                    "headline": f"Вывод номер {i}",
                    "fact_refs": ["f001"],
                }
                for i, intent in enumerate(intents, start=1)
            ],
        }

    def _slide(self) -> dict[str, Any]:
        """Слайд с явными координатами: плейсхолдеры у выбранного макета заранее
        неизвестны, а координаты внутри полей шаблона годятся для любого."""
        box = self.manifest.content_bbox
        return {
            "slide_id": "s01",
            "layout_id": self.manifest.layouts[0].layout_id,
            "variant": "A",
            "blocks": [
                {
                    "block_id": "b1",
                    "type": "text",
                    "role": TextRole.BODY.value,
                    "text": "Выручка выросла на 37,5 % за год",
                    "x": box.x,
                    "y": box.y,
                    "cx": box.cx,
                    "cy": box.cy // 4,
                }
            ],
        }


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    template = build_template(tmp_path / "template.pptx")

    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "факты.md").write_text(
        "# Итоги года\n\nВыручка выросла на 37,5 % за год.\n\nКлиентов стало более 500.\n",
        encoding="utf-8",
    )
    (content_dir / "не-контент.tmp").write_text("мусор", encoding="utf-8")

    brief = tmp_path / "brief.yaml"
    brief.write_text(
        "purpose: product\naudience: правление\ntarget_slides: 6\nlanguage: ru\n",
        encoding="utf-8",
    )
    return {"template": template, "content": content_dir, "brief": brief, "root": tmp_path}


def theme_fonts(tmp_path: Path, manifest: TemplateManifest) -> FontLibrary:
    directory = tmp_path / "fonts"
    directory.mkdir(exist_ok=True)
    for family in {manifest.theme.fonts.major_latin, manifest.theme.fonts.minor_latin}:
        make_font(directory, family, advance=500)
        make_font(directory, family, advance=550, bold=True)
    return FontLibrary([directory])


async def run_pipeline(
    workspace: dict[str, Path], checkpoint_path: Path | None = None, **overrides: Any
) -> tuple[RunResult, Deps]:
    root = workspace["root"]
    manifest = TemplateParser(cache_dir=root / "cache").parse(workspace["template"])
    out_dir = root / "artifacts" / "A"

    run = RunConfig(
        exports=overrides.pop("exports", ["pptx", "html"]),
        audit=overrides.pop("audit", {"run_semantic": False, "auto_fix": False}),
    )
    deps = Deps(
        brief=load_brief(workspace["brief"]),
        run=run,
        out_dir=out_dir,
        llm=FakeInference(manifest),
        fonts=theme_fonts(root, manifest),
        cache_dir=root / "cache",
        work_dir=out_dir,
        **overrides,
    )
    result = await generate_variant(
        workspace["template"],
        collect_content_paths(workspace["content"]),
        load_variant_profiles()["A"],
        deps,
        seed=1337,
        checkpoint_path=checkpoint_path,
        run_id="run1",
    )
    return result, deps


async def test_template_and_content_become_a_deck(workspace: dict[str, Path]) -> None:
    result, _ = await run_pipeline(workspace)

    assert not result.interrupted
    assert len(result.state["deck"].slides) == SLIDES_IN_PLAN
    assert result.exports["pptx"].is_file()
    assert result.exports["html"].is_file()
    assert result.state["audit"] is not None


async def test_every_stage_is_measured(workspace: dict[str, Path]) -> None:
    """Без таймингов по стадиям бюджет C5 не с чем сравнивать."""
    result, _ = await run_pipeline(workspace)
    timings = result.state["stage_timings_s"]
    assert {
        "parse_template",
        "ingest_content",
        "plan",
        "compose",
        "fit",
        "render",
        "audit",
        "export",
    } <= set(timings)


async def test_run_report_names_what_did_not_work(workspace: dict[str, Path]) -> None:
    result, _ = await run_pipeline(workspace)
    path = result.write_report()
    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["variant"] == "A"
    assert report["slides"] == SLIDES_IN_PLAN
    assert set(report["exports"]) == {"pptx", "html"}
    # Пропущенные проверки аудита — отдельная графа, а не растворённое «всё прошло».
    assert isinstance(report["skipped_checks"], list)
    assert report["total_s"] >= 0


async def test_layout_is_taken_from_the_template_not_from_the_model(
    workspace: dict[str, Path],
) -> None:
    """Подделка называет первый макет для каждого слайда; композитор обязан
    выбрать макет по виду и вместимости (change 11)."""
    result, _ = await run_pipeline(workspace)
    manifest = result.state["manifest"]
    used = {slide.layout_id for slide in result.state["deck"].slides}
    assert used <= {layout.layout_id for layout in manifest.layouts}
    kinds = {manifest.layout(layout_id).kind for layout_id in used}  # type: ignore[union-attr]
    assert kinds != {LayoutKind.TITLE} or len(manifest.layouts) == 1


async def test_pdf_without_libreoffice_is_reported_and_does_not_stop_the_run(
    workspace: dict[str, Path],
) -> None:
    """Отсутствие LibreOffice не повод остаться без pptx и html."""
    result, _ = await run_pipeline(workspace, exports=["pptx", "pdf", "html"])
    report = result.report()
    assert "pptx" in result.exports and "html" in result.exports
    if "pdf" not in result.exports:
        assert any("pdf не получен" in line for line in report["errors"])


async def test_unreadable_files_are_not_dragged_into_the_content_package(
    workspace: dict[str, Path],
) -> None:
    paths = collect_content_paths(workspace["content"])
    assert [p.name for p in paths] == ["факты.md"]


async def test_brief_comes_from_yaml_as_a_domain_model(workspace: dict[str, Path]) -> None:
    brief = load_brief(workspace["brief"])
    assert isinstance(brief, Brief) and brief.purpose == "product"


async def test_checkpoint_keeps_the_run_across_a_restart(workspace: dict[str, Path]) -> None:
    """Долгая задача обязана переживать перезапуск процесса: иначе HITL некуда вернуть."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path = workspace["root"] / "checkpoints.sqlite"
    result, _ = await run_pipeline(workspace, checkpoint_path=path)
    assert path.is_file()

    # Новое соединение — как после перезапуска: состояние читается с диска.
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        tuple_ = await saver.aget_tuple({"configurable": {"thread_id": "run1:A"}})
    assert tuple_ is not None, "чекпойнта нет — возобновлять нечего"
    assert "deck" in tuple_.checkpoint["channel_values"]
    assert result.state["deck"].deck_id == tuple_.checkpoint["channel_values"]["deck"].deck_id
