"""Узел `export`. Change (17) `pipeline-orchestration`.

Три формата из одного источника (C4): pptx уже записан узлом `render`, pdf получается
из него же, html собирается из того же `DeckIR`. Контент не пересобирается — иначе
форматы разъехались бы между собой.

Формат, который не получился, пропускается с причиной: отсутствие LibreOffice не повод
остаться без pptx и html.

Так было сказано с самого начала, но выполнялось только для pdf. Прогон `5cf2705fc173`
упал на html (`AttributeError` в `export/html.py`) — и унёс с собой уже записанные
`deck.pptx` и `deck.pdf`: файлы лежали в `out/`, а прогон считался `failed`, и в
интерфейсе «скачать» отдавало ошибку. Необязательный формат не уносит обязательный
(change `export-node-does-not-lose-the-deck`).

Рядом с колодой ложится дизайн-система шаблона — страница `design-system.html` и сама
структура `design-system.json` (Т2, change `design-system-in-the-run-folder`): по ним
проверяют, по какой системе собрана колода, не запуская `deckforge design-system`.
Это не формат колоды и не обязательный артефакт: не записалась — названо в ошибках,
колода остаётся.
"""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path

from langgraph.runtime import Runtime

from deckforge.designsystem import DesignSystem
from deckforge.export.design_system_page import render as render_design_system
from deckforge.export.html import export_html
from deckforge.export.pdf import ExportError, export_pdf
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState

DECK_STEM = "deck"
#: Имя файлов дизайн-системы в папке прогона — то же, что даёт команда `design-system`.
DESIGN_SYSTEM_STEM = "design-system"


def write_design_system(ds: DesignSystem, out_dir: Path) -> dict[str, Path]:
    """Страница дизайн-системы и её структура в папку прогона.

    Страница — та же функция, что у команды `deckforge design-system`, поэтому
    на одном шаблоне они совпадают байт в байт. JSON — сама `DesignSystem`: его можно
    сравнивать программой, а не глазами."""
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / f"{DESIGN_SYSTEM_STEM}.html"
    page.write_text(render_design_system(ds), encoding="utf-8")
    data = out_dir / f"{DESIGN_SYSTEM_STEM}.json"
    data.write_text(ds.model_dump_json(indent=2), encoding="utf-8")
    return {"html": page, "json": data}


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
                try:
                    exports["html"] = await asyncio.to_thread(
                        partial(
                            export_html,
                            deck,
                            state["manifest"],
                            deps.out_dir / f"{DECK_STEM}.html",
                            content=state["content"],
                            fonts=deps.fonts,
                            # Та же дизайн-система, что видели вписывание и pptx (DG3).
                            # Без неё html собирался по системе, посчитанной из манифеста,
                            # то есть по другой, чем колода, — и молча.
                            design_system=state.get("design_system"),
                        )
                    )
                except Exception as error:
                    # Ловится всё, а не свой тип ошибки: у pdf он есть (`ExportError`),
                    # у html такого нет, а цена узкого `except` здесь — выброшенная
                    # колода. Класс ошибки называется в отчёте, чтобы дефект не растворился
                    # в «html не получен»: прогон `5cf2705fc173` упал `AttributeError`,
                    # и это был настоящий баг, а не отсутствие внешней программы.
                    errors.append(f"html не получен: {type(error).__name__}: {error}")
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

        design_files: dict[str, Path] = {}
        design = state.get("design_system")
        if isinstance(design, DesignSystem):
            try:
                design_files = await asyncio.to_thread(
                    write_design_system, design, deps.out_dir
                )
            except Exception as error:
                # Та же причина широкого `except`, что у html: файл для проверки
                # не стоит готовой колоды.
                errors.append(
                    f"дизайн-система не записана: {type(error).__name__}: {error}"
                )

    return {
        "exports": exports,
        "design_system_files": design_files,
        "stage_timings_s": timings,
        "errors": errors,
    }
