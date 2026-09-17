"""C5: колода 10–15 слайдов за ≤ 300 с. Change (17), критерий гейта 20.09 (PLAN.md).

Тест бюджета имеет смысл только на живой модели: на подделке он мерил бы скорость
`json.dumps`. Поэтому он под `needs_llm` и пропускается без эндпоинта — CI в сеть
не ходит. Запуск на ml110:

    DECKFORGE_LLM_BASE_URL=... pytest tests/e2e/test_time_budget.py -m needs_llm -s

Шаблон синтетический (стандартный пакет python-pptx): бюджет меряется по пайплайну,
а не по конкретному шаблону организаторов.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deckforge.config import RunConfig
from deckforge.domain.content import Brief
from deckforge.inference.factory import client_for
from deckforge.layout.fonts import FontLibrary
from deckforge.pipeline.budget import STAGE_BUDGET_S
from deckforge.pipeline.deps import Deps
from deckforge.pipeline.run import collect_content_paths, generate_variant
from deckforge.registry import load_variant_profiles
from tests.integration.test_native_objects import build_template

TOTAL_BUDGET_S = 300
TARGET_SLIDES = 12
MIN_SLIDES, MAX_SLIDES = 10, 15

pytestmark = [
    pytest.mark.slow,
    pytest.mark.needs_llm,
    pytest.mark.skipif(
        not os.environ.get("DECKFORGE_LLM_BASE_URL"),
        reason="не задан DECKFORGE_LLM_BASE_URL — бюджет меряется только на живой модели",
    ),
]


async def test_deck_generated_within_budget(tmp_path: Path) -> None:
    template = build_template(tmp_path / "template.pptx")
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "материалы.md").write_text(
        "# Итоги года\n\n"
        "Выручка выросла на 37,5 % за год и составила 1 200 млн ₽.\n\n"
        "Клиентов стало более 500, отток снизился с 12 % до 4 %.\n\n"
        "Команда выросла вдвое: с 40 до 80 человек.\n",
        encoding="utf-8",
    )

    deps = Deps(
        brief=Brief(
            purpose="product",
            audience="правление компании",
            target_slides=TARGET_SLIDES,
            language="ru",
            key_message="Платформа вышла на окупаемость",
        ),
        run=RunConfig(exports=["pptx", "html"], audit={"run_semantic": False}),
        out_dir=tmp_path / "artifacts",
        llm=client_for("llm_main"),
        fonts=FontLibrary.default(),
        cache_dir=tmp_path / "cache",
        work_dir=tmp_path / "artifacts",
    )

    result = await generate_variant(
        template,
        collect_content_paths(content_dir),
        load_variant_profiles()["A"],
        deps,
        seed=1337,
    )
    report = result.report()
    _print_report(report)

    assert MIN_SLIDES <= report["slides"] <= MAX_SLIDES, "колода вне диапазона ТЗ"
    assert report["total_s"] <= TOTAL_BUDGET_S, (
        f"бюджет C5 превышен: {report['total_s']} с при пределе {TOTAL_BUDGET_S} с"
    )


def _print_report(report: dict[str, object]) -> None:
    """Печатает распределение по стадиям: превышение видно по строке, а не по итогу."""
    timings = report["stage_timings_s"]
    assert isinstance(timings, dict)
    print(f"\n\n=== Прогон {report['run_id']}, слайдов {report['slides']} ===")
    for stage, seconds in timings.items():
        budget = STAGE_BUDGET_S.get(stage)
        mark = " !!!" if budget is not None and seconds > budget else ""
        print(f"  {stage:<16} {seconds:7.1f} с  из {budget if budget else '—'}{mark}")
    print(f"  {'итого':<16} {report['total_s']:7.1f} с  из {TOTAL_BUDGET_S}")
    for line in [*report["degradations"], *report["errors"]]:  # type: ignore[misc]
        print(f"  ! {line}")
