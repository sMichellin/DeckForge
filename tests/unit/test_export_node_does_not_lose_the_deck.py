"""Необязательный формат не уносит готовую колоду. Change `export-node-does-not-lose-the-deck`.

Таск RG17 (`docs/agents/tasks-24-09.md`). Прогон `5cf2705fc173` (24.09) упал на html
`AttributeError`-ом — и унёс с собой уже записанные `deck.pptx` и `deck.pdf`: файлы
лежали в `out/`, а прогон считался `failed`, и в интерфейсе «скачать» отдавало ошибку.

Докстринг узла обещал обратное («Формат, который не получился, пропускается с причиной»)
с самого начала, но выполнялось это только для pdf: у него есть свой тип ошибки и
`except`, у html не было ни того, ни другого.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langgraph.runtime import Runtime

from deckforge.config import RunConfig
from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import DeckIR, FitResult, SlideIR, TextBlock
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import export as export_module
from deckforge.pipeline.nodes.export import export_node

BRIEF = Brief(purpose="report", audience="правление", target_slides=6)


def _state(manifest: TemplateManifest, tmp_path: Path) -> dict[str, Any]:
    title = manifest.typography(TextRole.TITLE)
    assert title is not None
    slide = SlideIR(
        slide_id="s01",
        layout_id="L07",
        variant="A",
        blocks=[TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Итоги")],
        fit_report={"t": FitResult(final_size_pt=title.size_pt)},
    )
    pptx = tmp_path / "deck.pptx"
    #: Настоящий пакет узлу не нужен: он только кладёт путь в `exports`.
    pptx.write_bytes(b"PK\x03\x04")
    return {
        "deck": DeckIR(
            deck_id="d", variant="A", template_id=manifest.template_id, seed=1, slides=[slide]
        ),
        "manifest": manifest,
        "content": ContentPackage(brief=BRIEF),
        "pptx_path": pptx,
    }


def _runtime(tmp_path: Path, formats: list[str]) -> Runtime[Deps]:
    return Runtime(
        context=Deps(
            brief=BRIEF,
            run=RunConfig(exports=formats),
            out_dir=tmp_path,
        )
    )


async def test_a_broken_html_does_not_take_the_pptx_with_it(
    manifest: TemplateManifest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Воспроизведение прогона `5cf2705fc173`: колода записана, html падает."""

    def explode(*args: object, **kwargs: object) -> Path:
        raise AttributeError("'NoneType' object has no attribute 'bbox'")

    monkeypatch.setattr(export_module, "export_html", explode)
    state = _state(manifest, tmp_path)

    result = await export_node(state, _runtime(tmp_path, ["pptx", "html"]))  # type: ignore[arg-type]

    assert result["exports"]["pptx"] == state["pptx_path"], "готовый pptx потерян"
    assert "html" not in result["exports"]
    assert result["errors"] == [
        "html не получен: AttributeError: 'NoneType' object has no attribute 'bbox'"
    ]


async def test_the_reason_names_the_kind_of_failure(
    manifest: TemplateManifest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Класс ошибки в отчёте: иначе настоящий баг растворится в «html не получен»."""

    def explode(*args: object, **kwargs: object) -> Path:
        raise ValueError("зона без рамки")

    monkeypatch.setattr(export_module, "export_html", explode)

    result = await export_node(
        _state(manifest, tmp_path), _runtime(tmp_path, ["html"])  # type: ignore[arg-type]
    )

    assert result["errors"] == ["html не получен: ValueError: зона без рамки"]


async def test_html_gets_the_same_design_system_as_the_deck(
    manifest: TemplateManifest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DG3: html собирается по той же дизайн-системе, что вписывание и pptx.

    Узел её не передавал, и html молча считал свою из манифеста — то есть другую.
    """
    seen: dict[str, object] = {}

    def spy(*args: object, **kwargs: object) -> Path:
        seen.update(kwargs)
        out = tmp_path / "deck.html"
        out.write_text("<html></html>", encoding="utf-8")
        return out

    monkeypatch.setattr(export_module, "export_html", spy)
    state = _state(manifest, tmp_path)
    marker = object()
    state["design_system"] = marker

    result = await export_node(state, _runtime(tmp_path, ["html"]))  # type: ignore[arg-type]

    assert result["errors"] == []
    assert seen.get("design_system") is marker, "дизайн-система до html не доехала"


async def test_a_working_html_is_still_exported(
    manifest: TemplateManifest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Норма: исправный html по-прежнему попадает в результат, ошибок нет."""

    def ok(*args: object, **kwargs: object) -> Path:
        out = tmp_path / "deck.html"
        out.write_text("<html></html>", encoding="utf-8")
        return out

    monkeypatch.setattr(export_module, "export_html", ok)

    result = await export_node(
        _state(manifest, tmp_path), _runtime(tmp_path, ["pptx", "html"])  # type: ignore[arg-type]
    )

    assert set(result["exports"]) == {"pptx", "html"}
    assert result["errors"] == []
