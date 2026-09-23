#!/usr/bin/env python3
"""Сводка по прогонам: медиана и разброс, а не один прогон.

Разброс модели между одинаковыми прогонами больше, чем польза иной правки: на одном
и том же коде, материале и seed заголовки укладывались в рамку то 9 раз из 10, то 5.
Сравнивать по одному прогону — значит принимать шум за результат; в работах по оценке
LLM это называют прямо: «an alarming degree of variation across equivalent input runs
with high-performing LLMs under presumed deterministic settings» (arXiv:2408.04667),
и лечится повторами с разбросом, а не более точным единичным замером.

Скрипт читает готовые каталоги прогонов (`data/runs/<id>/`) и печатает по каждой метрике
медиану и границы. Ничего не запускает: прогоны делает стенд, здесь только счёт.

    python scripts/run_metrics.py data/runs/129cb896900c data/runs/ed84aa87620c …
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

#: Заметки, по которым видно исход, важный для качества колоды.
_TRIMMED = "подрезан под рамку"
_FACT_LOST = "на слайд не попали"
_VISUAL_BLOCKS = {"kpi", "smartart", "chart", "table"}


def _slides(checkpoint: Path) -> list[dict[str, Any]]:
    """Слайды из чекпойнта LangGraph. Пусто — чекпойнта нет или он другой версии."""
    if not checkpoint.is_file():
        return []
    try:
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    except ImportError:
        return []

    serde = JsonPlusSerializer()
    found: dict[str, dict[str, Any]] = {}
    with sqlite3.connect(checkpoint) as connection:
        rows = connection.execute("select channel, type, value from writes order by rowid")
        for channel, kind, value in rows:
            if channel != "slides":
                continue
            payload = serde.loads_typed((kind, value))
            for item in payload if isinstance(payload, list) else [payload]:
                data = item if isinstance(item, dict) else item.model_dump()
                found[data["slide_id"]] = data
    return list(found.values())


def metrics(run_dir: Path) -> dict[str, float]:
    """Метрики одного прогона. Отсутствующее не выдумывается, а пропускается."""
    report = json.loads((run_dir / "out" / "run.json").read_text(encoding="utf-8"))
    notes = report.get("notes") or []
    slides = _slides(run_dir / "checkpoint.sqlite")
    audit = report.get("audit") or {}

    out: dict[str, float] = {
        "слайдов": float(report.get("slides") or 0),
        "секунд": float(report.get("total_s") or 0),
        "ошибок аудита": float(audit.get("errors") or 0),
        "предупреждений": float(audit.get("warnings") or 0),
        "заголовков подрезано": float(sum(1 for note in notes if _TRIMMED in note)),
        "фактов потеряно": float(sum(1 for note in notes if _FACT_LOST in note)),
    }
    if slides:
        visuals = sum(
            1
            for slide in slides
            for block in slide.get("blocks", [])
            if block.get("type") in _VISUAL_BLOCKS
        )
        out["визуализаций"] = float(visuals)
    out.update(_design(report.get("design_metrics") or {}))
    usage = report.get("design_system_usage")
    if usage:
        # Доля слайдов, собранных с элементом дизайн-системы (`design-system-usage-in-the-run`).
        out["слайдов с элементом ДС, %"] = round(100 * float(usage.get("share") or 0), 1)
    return out


#: Пустая зона такой доли ширины и высоты считается дырой рядом с содержанием, а не
#: воздухом. Те же числа, что у порогов `design.ink_balance` (B8: «≥ 40 % ширины»).
_WIDE_ZONE = 0.4


def _design(by_slide: dict[str, dict[str, float]]) -> dict[str, float]:
    """Оформление колоды одной строкой на метрику. Задача C7.

    Медиана, а не среднее: один титул с большим полем не должен решать за колоду.
    Доля слайдов с широкой пустой зоной — целевая метрика B8; она считается по колоде,
    а не по находкам, потому что находка есть только у слайда за порогом.
    """
    values = [item for item in by_slide.values() if item]
    if not values:
        return {}
    wide = [
        item
        for item in values
        if item.get("zone_w", 0) >= _WIDE_ZONE and item.get("zone_h", 0) >= _WIDE_ZONE
    ]
    out = {
        "чернил, % (медиана)": round(
            statistics.median(item.get("ink", 0.0) for item in values) * 100, 2
        ),
        "дисбаланс (медиана)": round(
            statistics.median(item.get("imbalance", 0.0) for item in values), 2
        ),
        "слайдов с пустой зоной, %": round(100 * len(wide) / len(values), 1),
    }
    if not all(item.get("chrome") for item in values):
        # Без превью пустых макетов метрики считают декор шаблона содержанием (C9):
        # сравнивать такой прогон с прогоном, где превью были, нельзя.
        out["без превью макетов, слайдов"] = float(
            sum(1 for item in values if not item.get("chrome"))
        )
    return out


def _fmt(value: float) -> str:
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"


def main(argv: list[str]) -> int:
    runs = [Path(item) for item in argv]
    if not runs:
        print(__doc__)
        return 2

    rows: dict[str, dict[str, float]] = {}
    for run in runs:
        try:
            rows[run.name] = metrics(run)
        except (OSError, json.JSONDecodeError, KeyError) as error:
            print(f"{run.name}: пропущен — {error}")

    if not rows:
        return 1

    names = sorted({name for values in rows.values() for name in values})
    width = max(len(name) for name in names) + 2
    header = "".join(f"{run:>14}" for run in rows)
    print(f"{'метрика':<{width}}{header}{'медиана':>12}{'разброс':>14}")
    for name in names:
        values = [rows[run][name] for run in rows if name in rows[run]]
        cells = "".join(
            f"{_fmt(rows[run][name]):>14}" if name in rows[run] else f"{'—':>14}"
            for run in rows
        )
        spread = f"{_fmt(min(values))}–{_fmt(max(values))}" if len(values) > 1 else "—"
        print(f"{name:<{width}}{cells}{_fmt(statistics.median(values)):>12}{spread:>14}")

    if len(rows) < 3:
        print(
            "\nПрогонов меньше трёх: разброс по ним ни о чём не говорит. "
            "Правку стоит сравнивать по трём и более прогонам на каждой стороне."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main([item for item in sys.argv[1:] if not re.match(r"^-", item)]))
