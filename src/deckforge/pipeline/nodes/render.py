"""Узел `render`. Change (17) `pipeline-orchestration`.

Здесь колода впервые становится файлом, и здесь же снимаются превью для аудита.
Превью требуют LibreOffice, которого в образе приложения нет (он в образе воркера):
без него узел отдаёт пустой словарь и причину, а проверки, которым нечего смотреть,
сами уходят в пропущенные (change 15). Колода собирается в любом случае.
"""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path

from langgraph.runtime import Runtime

from deckforge.audit.preview import SofficeUnavailableError, render_deck_previews
from deckforge.export.pptx import export_pptx
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState

DECK_FILENAME = "deck.pptx"


async def render_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """`DeckIR` → нативный .pptx (changes 13, 14, 21) и превью для аудита (change 6)."""
    deps = runtime.context
    deck = state["deck"]
    out = deps.out_dir / DECK_FILENAME

    notes: list[str] = []
    degradations: list[str] = []
    previews: dict[str, Path] = {}

    # Превью нужны не только судье-VLM: по картинке слайда считаются метрики оформления
    # (`design.ink_balance`), а они детерминированные и идут всегда. Рендер десяти
    # страниц стоит секунды, и без него проверка уходит в пропущенные — то есть колода
    # снова оценивается по рамкам, а не по тому, как выглядит.
    wants_previews = bool(deps.run.audit.get("run_deterministic", True)) or (
        bool(deps.run.audit.get("run_semantic", True)) and deps.vlm is not None
    )
    if wants_previews and deps.budget.behind_schedule("render"):
        wants_previews = False
        degradations.append("render: превью не снимаются — остатка бюджета не хватает (§15)")

    async with timed(deps, "render") as timings:
        pptx_path = await asyncio.to_thread(
            partial(
                export_pptx,
                deck,
                state["manifest"],
                state["template_path"],
                out,
                content=state["content"],
                fonts=deps.fonts,
            )
        )
        if wants_previews:
            try:
                previews = dict(
                    await asyncio.to_thread(
                        partial(render_deck_previews, pptx_path, deck, deps.previews_dir())
                    )
                )
            except (SofficeUnavailableError, OSError) as error:
                notes.append(f"превью не сняты ({error}): проверки по изображению будут пропущены")

    return {
        "pptx_path": pptx_path,
        "previews": previews,
        "stage_timings_s": timings,
        "notes": notes,
        "degradations": degradations,
    }
