#!/usr/bin/env python3
"""Девять презентаций для сдачи (A3, PLAN.md §6): 3 шаблона × 3 варианта, один контент.

Раскладка результата:
    submission/decks/<template>/<variant>/{deck.pptx,deck.pdf,deck.html,audit_report.json}
    submission/decks/metrics.md   — время генерации каждой колоды

Seed фиксирован конфигом: повторный запуск даёт тот же результат (C11).
"""

from __future__ import annotations

from pathlib import Path

TEMPLATES_DEFAULT = Path("tests/fixtures/templates")
OUT = Path("submission/decks")


def main() -> int:
    raise NotImplementedError("сборка пакета сдачи, 26.09 (PLAN.md §6)")


if __name__ == "__main__":
    raise SystemExit(main())
