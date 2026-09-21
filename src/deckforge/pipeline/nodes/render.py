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

from deckforge.audit.preview import (
    SofficeUnavailableError,
    render_deck_previews,
    render_layout_previews,
)
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
    layout_previews: dict[str, Path] = {}

    # Превью нужны не только судье-VLM: по картинке слайда считаются метрики оформления
    # (`design.ink_balance`), а они детерминированные и идут всегда. Рендер десяти
    # страниц стоит секунды, и без него проверка уходит в пропущенные — то есть колода
    # снова оценивается по рамкам, а не по тому, как выглядит.
    for_design = bool(deps.run.audit.get("run_deterministic", True))
    for_judge = bool(deps.run.audit.get("run_semantic", True)) and deps.vlm is not None
    wants_previews = for_design or for_judge
    # Рычаг бюджета снимает превью, только если они нужны одному судье-VLM: судья —
    # десятки минут, а рендер — секунды. Прогон d973a7ee8110 отстал от расписания,
    # простояв в очереди к модели 51 минуту, и рычаг «сэкономил» три секунды рендера —
    # ценой детерминированной проверки оформления, которая ушла в пропущенные.
    if wants_previews and not for_design and deps.budget.behind_schedule("render"):
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

        # Пустые макеты (C9): метрики оформления вычитают их из превью слайда, иначе
        # логотип и плашки шаблона считаются содержанием и тянут центр тяжести.
        # Без них проверка не пропускается, а считает как прежде, поэтому неудача здесь —
        # это оговорка, а не потеря проверки.
        if previews:
            try:
                layout_previews = dict(
                    await asyncio.to_thread(
                        partial(
                            render_layout_previews,
                            state["template_path"],
                            state["manifest"],
                            deps.previews_dir() / "layouts",
                            {slide.layout_id for slide in deck.slides},
                        )
                    )
                )
            # Широкий перехват намеренно: макет читает python-pptx, а пустые макеты —
            # не обязательная часть колоды. Любая их неудача обязана остаться оговоркой,
            # а не уронить рендер уже собранного файла.
            except Exception as error:
                notes.append(
                    f"превью пустых макетов не сняты ({error}): метрики оформления "
                    "посчитают декор шаблона содержанием"
                )

    return {
        "pptx_path": pptx_path,
        "previews": previews,
        "layout_previews": layout_previews,
        "stage_timings_s": timings,
        "notes": notes,
        "degradations": degradations,
    }
