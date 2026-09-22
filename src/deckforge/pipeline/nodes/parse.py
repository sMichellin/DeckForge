"""Узел `parse`. Change (17) `pipeline-orchestration`, DG2 `design-system-in-the-pipeline`."""

from __future__ import annotations

import asyncio
from pathlib import Path

from langgraph.runtime import Runtime

from deckforge.config import get_settings
from deckforge.designsystem import DesignSystem, derive
from deckforge.domain.template import TemplateManifest
from deckforge.parsing.layout_kind import LayoutClassifier
from deckforge.parsing.template import TemplateParser
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.nodes import timed
from deckforge.pipeline.state import DeckState


def _parse_and_derive(
    parser: TemplateParser, path: Path
) -> tuple[TemplateManifest, DesignSystem]:
    """Манифест и его дизайн-система — одним заходом в поток.

    ДС считается всегда, в том числе на манифесте из кэша: кэшируется источник,
    а не производные. Второй кэш дал бы вторую причину его инвалидировать, а `derive` —
    чистая функция без модели и без файлов, и пересчёт стоит доли секунды (DG2).
    """
    manifest = parser.parse(path)
    return manifest, derive(manifest)


async def parse_node(state: DeckState, runtime: Runtime[Deps]) -> DeckState:
    """Шаблон → `TemplateManifest` и `DesignSystem` (changes 3–6, DG2).

    Идёт параллельно с ingestion. ДС считается здесь, а не отдельным узлом: без манифеста
    её не существует, и развилки между ними нет.
    """
    deps = runtime.context
    # Предел времени на модель: очередь к общему однослотовому серверу ничем
    # не ограничена, и незнакомый шаблон разбирался 2375 с при бюджете стадии 25 с
    # (прогон aa5eca9aa135). Ноль в настройке снимает предел.
    budget_s = get_settings().layout_vlm_budget_s
    classifier = LayoutClassifier(
        vlm=deps.layout_vlm,
        language=deps.brief.language,
        profile=deps.prompt_profile,
        base_seed=state["seed"],
        budget_s=budget_s if budget_s > 0 else None,
    )
    parser = TemplateParser(cache_dir=deps.cache_dir, classifier=classifier)
    async with timed(deps, "parse_template") as timings:
        # Парсер синхронный и упирается в диск: поток освобождает цикл событий
        # для ingestion, который идёт в это же время. `derive` — там же и внутри
        # замера: её стоимость — часть стадии, а не невидимая добавка к ней.
        manifest, design_system = await asyncio.to_thread(
            _parse_and_derive, parser, state["template_path"]
        )

    notes: list[str] = []
    degradations: list[str] = []
    if deps.layout_vlm is None:
        notes.append("классификация макетов: без VLM, только эвристика (change 5)")
    if classifier.overdue:
        # Рычаг §15: качество разметки разменяно на время. Молчать об этом нельзя —
        # иначе откат на эвристику неотличим от согласия модели с эвристикой.
        degradations.append(
            f"parse_template: предел {budget_s:g} с на разметку макетов моделью исчерпан, "
            f"макетов размечено эвристикой: {classifier.fell_back} (§15)"
        )
    return {
        "manifest": manifest,
        "design_system": design_system,
        "stage_timings_s": timings,
        "notes": notes,
        "degradations": degradations,
    }
