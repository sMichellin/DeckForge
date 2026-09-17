"""Узел `export`. Change (17) `pipeline-orchestration`.

Три формата из одного источника (C4): pptx уже записан узлом `render`, pdf получается
из него же, html собирается из того же `DeckIR`. Контент не пересобирается — иначе
форматы разъехались бы между собой.

Формат, который не получился, пропускается с причиной: отсутствие LibreOffice не повод
остаться без pptx и html.
"""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path

from langgraph.runtime import Runtime

from deckforge.export.html import export_html
from deckforge.export.pdf import ExportError, export_pdf
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState

DECK_STEM = "deck"


async def export_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """pptx / pdf / html по списку `exports` конфига (changes 16, 22)."""
    deps = runtime.context
    deck = state["deck"]
    pptx_path = state.get("pptx_path")

    exports: dict[str, Path] = {}
    errors: list[str] = []

    async with timed(deps, "export") as timings:
        for fmt in deps.run.exports:
            if fmt == "pptx":
                if pptx_path is not None:
                    exports["pptx"] = pptx_path
                continue
            if fmt == "html":
                exports["html"] = await asyncio.to_thread(
                    partial(
                        export_html,
                        deck,
                        state["manifest"],
                        deps.out_dir / f"{DECK_STEM}.html",
                        content=state["content"],
                        fonts=deps.fonts,
                    )
                )
                continue
            if fmt == "pdf":
                if pptx_path is None:
                    errors.append("pdf не получен: нет исходного .pptx")
                    continue
                try:
                    exports["pdf"] = await asyncio.to_thread(
                        partial(export_pdf, pptx_path, deps.out_dir / f"{DECK_STEM}.pdf")
                    )
                except ExportError as error:
                    errors.append(f"pdf не получен: {error}")
                continue
            errors.append(f"формат {fmt!r} не поддерживается: pptx, pdf, html")

    return {"exports": exports, "stage_timings_s": timings, "errors": errors}
