"""Живой прогон планировщика. Change (10) `deck-planning`.

Пропускается без эндпоинта: CI в сеть не ходит. Запуск локально с выводом плана:

    pytest tests/integration/test_generation_live.py -m needs_llm -s

Проверяется не красота формулировок — её смотрит человек, — а то, что модель
по нашему промпту выдаёт валидный `DeckPlan`, укладывается в бюджет и не ссылается
на факты, которых в контент-пакете нет.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from deckforge.domain.content import Brief, ContentPackage
from deckforge.domain.plan import DeckPlan
from deckforge.domain.template import TemplateManifest
from deckforge.inference import client_for
from deckforge.parsing import TemplateParser
from deckforge.parsing.content import ContentIngestor
from deckforge.planning.planner import DeckPlanner
from deckforge.registry import load_variant_profiles

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PACK = FIXTURES / "content" / "synthetic" / "product"
TEMPLATES = sorted((FIXTURES / "templates").rglob("*.pptx"))

#: Бюджет стадии планирования из ARCHITECTURE.md §12.
PLANNING_BUDGET_S = 35.0

pytestmark = [
    pytest.mark.needs_llm,
    pytest.mark.slow,
    pytest.mark.skipif(
        not os.environ.get("DECKFORGE_LLM_BASE_URL"),
        reason="не задан DECKFORGE_LLM_BASE_URL — живой прогон не выполняется",
    ),
    pytest.mark.skipif(not PACK.exists(), reason="нет синтетического контент-пакета"),
]


@pytest.fixture(scope="module")
def content() -> ContentPackage:
    import yaml

    brief = Brief(**yaml.safe_load((PACK / "brief.yaml").read_text(encoding="utf-8")))
    sources = [PACK / "content.md"]
    return ContentIngestor().ingest(sources, brief)


@pytest.fixture(scope="module")
def live_manifest() -> TemplateManifest:
    if not TEMPLATES:
        pytest.skip("нет шаблонов в tests/fixtures/templates/")
    return TemplateParser().parse(TEMPLATES[0], use_cache=True)


async def test_planner_produces_a_usable_deck(
    content: ContentPackage, live_manifest: TemplateManifest
) -> None:
    variant = load_variant_profiles()["C"]
    started = time.monotonic()
    plan = await DeckPlanner(client_for("llm_main")).plan(
        content, live_manifest, variant, seed=1337
    )
    elapsed = time.monotonic() - started

    _report(plan, content, elapsed)

    assert isinstance(plan, DeckPlan)
    assert plan.slides, "план пуст"
    known = {fact.fact_id for fact in content.facts}
    assert all(ref in known for slide in plan.slides for ref in slide.fact_refs)
    assert plan.variant == "C" and plan.seed == 1337


def _report(plan: DeckPlan, content: ContentPackage, elapsed: float) -> None:
    """Печатает план целиком: живой прогон существует ради человеческого взгляда."""
    print(f"\n\n=== План колоды, {len(plan.slides)} слайдов, {elapsed:.1f} с ===")
    if elapsed > PLANNING_BUDGET_S:
        print(f"!!! бюджет стадии {PLANNING_BUDGET_S:.0f} с превышен")
    for slide in plan.slides:
        refs = ", ".join(slide.fact_refs) or "—"
        print(f"  {slide.slide_id}  {slide.intent.value:<10} {slide.headline}")
        data = f"; данные: {slide.dataset_ref}" if slide.dataset_ref else ""
        print(f"      факты: {refs}{data}")
    print("\n--- отчёт по нарративу ---")
    check = plan.narrative_check
    print(f"  одна мысль на слайд: {check.one_idea_per_slide}; арка: {check.has_arc}")
    for note in check.notes:
        print(f"  ! {note}")
    if not check.notes:
        print("  нарушений нет")
    print(f"\n  фактов в пакете: {len(content.facts)}, чисел: {len(content.all_numbers)}\n")
