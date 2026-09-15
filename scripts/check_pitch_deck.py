#!/usr/bin/env python3
"""Одноразовый гейт питч-колоды (PLAN.md §5): слайды 7–11 не изменены.

Сравнивает структуру XML слайдов 7–11 итогового файла с исходным шаблоном.
Отличия допускаются только в текстовых значениях там, где шаблон их предполагает.
"""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_RANGE = range(7, 12)


def main(template: Path, deck: Path) -> int:
    raise NotImplementedError("подготовка питча, 26.09 (PLAN.md §5)")


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
