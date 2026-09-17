"""Узел `fit`. Change (17) `pipeline-orchestration`."""

from __future__ import annotations

import asyncio

from langgraph.runtime import Runtime

from deckforge.domain.slide import DeckIR, SlideIR
from deckforge.layout.errors import LayoutFitError
from deckforge.layout.fitting import fit_slide
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState


def _ordered(state: DeckState) -> list[SlideIR]:
    """Порядок колоды — из плана.

    Редьюсер состояния хранит слайды словарём по `slide_id`, а идентификаторы придумывает
    модель: сортировка строк поставила бы «s10» перед «s9». Единственный источник порядка —
    последовательность плана.
    """
    by_id = {slide.slide_id: slide for slide in state["slides"]}
    return [by_id[s.slide_id] for s in state["plan"].slides if s.slide_id in by_id]


async def fit_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """Вписывание текста метриками гарнитуры до записи файла (change 12)."""
    deps = runtime.context
    manifest = state["manifest"]
    plan = state["plan"]

    def work() -> tuple[list[SlideIR], list[str]]:
        fitted: list[SlideIR] = []
        failed: list[str] = []
        for slide in _ordered(state):
            try:
                fitted.append(
                    fit_slide(slide, manifest, fonts=deps.fonts, content=state["content"])
                )
            except LayoutFitError as error:
                failed.append(f"слайд {slide.slide_id} не вписан: {error}")
        return fitted, failed

    async with timed(deps, "fit") as timings:
        fitted, failed = await asyncio.to_thread(work)

    if not fitted:
        raise RuntimeError(f"ни один слайд не вписан: {'; '.join(failed)}")

    deck = DeckIR(
        deck_id=plan.deck_id,
        variant=state["variant"].variant_id,
        template_id=manifest.template_id,
        language=plan.language,
        seed=state["seed"],
        slides=fitted,
    )
    return {"deck": deck, "slides": fitted, "stage_timings_s": timings, "errors": failed}
