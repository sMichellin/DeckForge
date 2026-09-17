#!/usr/bin/env python3
"""Замер бюджета C5 по стадиям (§12). Печатает таблицу и p95 по N прогонам. Change (17).

Тест `tests/e2e/test_time_budget.py` отвечает «уложились или нет» одним прогоном. Этот
скрипт отвечает на другой вопрос — **куда уходит время и насколько разброс велик**:
p95 по одному прогону не считается, а решение «понижать ли `llm_main` до `llm_fast`»
принимается именно по разбросу.

    DECKFORGE_LLM_BASE_URL=... DECKFORGE_LLM_API_KEY=... \
    python scripts/bench_time_budget.py шаблон.pptx контент/ --brief brief.yaml --runs 5

Живая модель обязательна: на подделке скрипт мерил бы скорость `json.dumps`.
Кэш ответов инференса при замере стоит выключать (`DECKFORGE_...`-профиль без кэша),
иначе второй прогон покажет время чтения с диска, а не время модели.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deckforge.config import load_run_config
from deckforge.pipeline.budget import STAGE_BUDGET_S, STAGE_ORDER, TOTAL_BUDGET_S
from deckforge.pipeline.run import (
    RunResult,
    build_deps,
    collect_content_paths,
    generate_variant,
    load_brief,
    variants_for,
)


def percentile(values: list[float], fraction: float) -> float:
    """Персентиль по ближайшему рангу: на трёх прогонах интерполяция врёт сильнее."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * len(ordered) + 0.5) - 1))
    return ordered[index]


def run_once(
    template: Path, content: list[Path], brief_path: Path, profile: str | None, variant: str
) -> RunResult:
    run = load_run_config(profile=profile)
    with tempfile.TemporaryDirectory() as work:
        deps = build_deps(
            load_brief(brief_path),
            run,
            Path(work) / "out",
            cache_dir=Path(work) / "cache",
            asset_dir=Path(work) / "assets",
        )
        return asyncio.run(
            generate_variant(
                template, content, variants_for([variant])[0], deps, seed=run.seed
            )
        )


def table(results: list[RunResult]) -> dict[str, list[float]]:
    """Тайминги по стадиям, собранные со всех прогонов."""
    per_stage: dict[str, list[float]] = {}
    for result in results:
        for stage, seconds in (result.state.get("stage_timings_s") or {}).items():
            per_stage.setdefault(stage, []).append(seconds)
    return per_stage


def report(results: list[RunResult], budget_s: int) -> bool:
    """Печатает распределение и возвращает, уложился ли p95 в бюджет."""
    per_stage = table(results)
    totals = [sum((r.state.get("stage_timings_s") or {}).values()) for r in results]

    print(f"\nпрогонов: {len(results)}, слайдов: {[r.report()['slides'] for r in results]}")
    print(f"\n{'стадия':<16} {'медиана':>9} {'макс':>9} {'бюджет':>8}")
    print("-" * 46)
    known = [s for s in STAGE_ORDER if s in per_stage]
    for stage in [*known, *sorted(set(per_stage) - set(known))]:
        values = per_stage[stage]
        budget = STAGE_BUDGET_S.get(stage)
        mark = " !!!" if budget is not None and max(values) > budget else ""
        print(
            f"{stage:<16} {statistics.median(values):>9.1f} {max(values):>9.1f} "
            f"{budget if budget is not None else '—':>8}{mark}"
        )

    p95 = percentile(totals, 0.95)
    print("-" * 46)
    print(f"{'итого медиана':<16} {statistics.median(totals):>9.1f}")
    print(f"{'итого p95':<16} {p95:>9.1f}   из {budget_s}")

    # Всё, что не отработало, называется здесь: замер времени на колоде без половины
    # слайдов — это замер другого пайплайна.
    for index, result in enumerate(results, start=1):
        data = result.report()
        for line in [*data["degradations"], *data["errors"]]:
            print(f"  ! прогон {index}: {line}")

    return p95 <= budget_s


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path)
    parser.add_argument("content", type=Path)
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--variant", default="A")
    parser.add_argument("--profile", default=None, help="Профиль configs/profiles/<имя>.yaml")
    parser.add_argument("--out", type=Path, help="Куда сложить тайминги в json")
    args = parser.parse_args()

    paths = collect_content_paths(args.content)
    results = [
        run_once(args.template, paths, args.brief, args.profile, args.variant)
        for _ in range(max(1, args.runs))
    ]

    budget_s = load_run_config(profile=args.profile).time_budget_s or TOTAL_BUDGET_S
    ok = report(results, budget_s)

    if args.out:
        args.out.write_text(
            json.dumps(
                {"budget_s": budget_s, "runs": [r.report() for r in results]},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"\nнаписано {args.out}")

    # Ненулевой код возврата — чтобы замер годился в гейт, а не только для чтения глазами.
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
