"""DG2 на настоящем разборе: ДС из узла `parse` переживает чекпойнт sqlite.

Граф здесь — один узел `parse_template` с тем же чекпойнтером, что у прогона
(`open_checkpointer`): проверяется, что новое поле состояния сериализуется и поднимается
обратно тем же классом, а не словарём. Остальные узлы к этому ничего не добавляют,
а без модели их не пройти.

Шаблон — стандартный шаблон python-pptx: не принадлежит организаторам и не похож
на их шаблоны (C6).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.graph import END, START, StateGraph

from deckforge.config import RunConfig
from deckforge.designsystem import DesignSystem, derive
from deckforge.domain.content import Brief
from deckforge.parsing import TemplateParser
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes.parse import parse_node
from deckforge.pipeline.run import design_system_summary, open_checkpointer
from deckforge.pipeline.state import DeckState
from tests.integration.test_native_objects import build_template

THREAD = {"configurable": {"thread_id": "dg2:A"}}


def _deps(root: Path) -> Deps:
    brief = Brief(purpose="product", audience="правление", target_slides=6, language="ru")
    return Deps(brief=brief, run=RunConfig(), out_dir=root, cache_dir=root / "cache")


async def _parse_with_checkpoint(template: Path, root: Path, checkpoint: Path) -> DeckState:
    graph: StateGraph[DeckState, Deps, DeckState, DeckState] = StateGraph(
        DeckState, context_schema=Deps
    )
    graph.add_node("parse_template", parse_node)
    graph.add_edge(START, "parse_template")
    graph.add_edge("parse_template", END)
    async with open_checkpointer(checkpoint) as saver:
        compiled = graph.compile(checkpointer=saver)
        state: DeckState = {"run_id": "dg2", "seed": 1, "template_path": template}
        final: DeckState = await compiled.ainvoke(state, config=THREAD, context=_deps(root))
    return final


async def _restored(checkpoint: Path) -> dict[str, object]:
    """Новое соединение — как после перезапуска процесса: состояние читается с диска."""
    async with open_checkpointer(checkpoint) as saver:
        stored = await saver.aget_tuple(THREAD)
    assert stored is not None, "чекпойнта нет — поднимать нечего"
    values: dict[str, object] = stored.checkpoint["channel_values"]
    return values


async def test_design_system_survives_the_sqlite_checkpoint(tmp_path: Path) -> None:
    template = build_template(tmp_path / "template.pptx")
    checkpoint = tmp_path / "checkpoints.sqlite"

    final = await _parse_with_checkpoint(template, tmp_path, checkpoint)
    values = await _restored(checkpoint)

    restored = values["design_system"]
    assert isinstance(restored, DesignSystem), f"поднялся {type(restored).__name__}"
    assert restored == final["design_system"]
    assert restored == derive(final["manifest"])
    assert restored.template_id == final["manifest"].template_id


@pytest.mark.cold
async def test_cold_template_gets_a_design_system_with_empty_measured_sections(
    tmp_path: Path,
) -> None:
    """Правило 10: шаблон без слайдов-примеров. ДС собирается, мерить в ней нечего."""
    template = build_template(tmp_path / "cold.pptx", sample_slides=0)
    checkpoint = tmp_path / "checkpoints.sqlite"

    final = await _parse_with_checkpoint(template, tmp_path, checkpoint)

    assert final["manifest"].examples == []
    ds = final["design_system"]
    assert ds.palette_roles == []
    assert ds.combinations == []
    assert ds.fonts_in_use == []
    assert ds.components == []
    # Производное от темы и сетки на месте: холодный шаблон — не пустая ДС.
    summary = design_system_summary(ds)
    assert summary is not None
    assert summary["type_levels"] > 0 and summary["theme_slots"] > 0
    assert (await _restored(checkpoint))["design_system"] == ds


async def test_cached_manifest_gives_the_same_design_system(tmp_path: Path) -> None:
    """Второй прогон берёт манифест из кэша, а ДС считает заново — и она та же."""
    template = build_template(tmp_path / "template.pptx")
    parser = TemplateParser(cache_dir=tmp_path / "cache")
    parser.parse(template)
    assert parser.load_cached(parser.parse(template).template_id) is not None

    first = await _parse_with_checkpoint(template, tmp_path, tmp_path / "one.sqlite")
    second = await _parse_with_checkpoint(template, tmp_path, tmp_path / "two.sqlite")

    assert first["design_system"] == second["design_system"]
