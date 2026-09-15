#!/usr/bin/env python3
"""CI-гейт C6: в `src/` нет констант, зашитых под конкретный шаблон.

Запрещено: литеральные RGB (#RRGGBB, RGBColor(...)), имена гарнитур, крупные числа EMU,
имена макетов. Всё это берётся из `TemplateManifest`.

Исключения: `deckforge/domain/units.py` (единицы измерения) и строки в docstring-примерах.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
#: Единственный модуль, где литералы геометрии — по определению не «константы шаблона»,
#: а единицы измерения формата.
ALLOWLIST = {"deckforge/domain/units.py"}

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("литеральный цвет", re.compile(r"#[0-9A-Fa-f]{6}\b")),
    ("RGBColor с литералом", re.compile(r"RGBColor\s*\(\s*0x|RGBColor\s*\(\s*\d+")),
    (
        "имя гарнитуры",
        re.compile(
            r"[\"'](?:Montserrat|Inter|Calibri|Arial|Roboto|Helvetica|Times New Roman|"
            r"Open Sans|Lato|PT Sans|Tahoma|Verdana)[\"']"
        ),
    ),
    # Разделители разрядов (1_200_000) не должны быть лазейкой: цифра плюс подчёркивания.
    ("размер в EMU литералом", re.compile(r"(?<![\w.])\d[\d_]{4,}(?![\w.])")),
    ("Pt/Emu/Inches с литералом", re.compile(r"\b(?:Pt|Emu|Inches|Cm)\s*\(\s*\d")),
]

COMMENT_OR_DOC = re.compile(r"^\s*#|^\s*[\"']{3}|^\s*\*|^\s*\|")


def scan(path: Path) -> list[str]:
    rel = path.relative_to(SRC).as_posix()
    if rel in ALLOWLIST:
        return []
    problems: list[str] = []
    in_doc = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.count('"""') % 2 == 1:
            in_doc = not in_doc
            continue
        if in_doc or COMMENT_OR_DOC.match(line):
            continue
        for label, pattern in PATTERNS:
            if pattern.search(line):
                problems.append(f"{rel}:{lineno}: {label} — {stripped[:90]}")
    return problems


def main() -> int:
    problems = [p for f in sorted(SRC.rglob("*.py")) for p in scan(f)]
    if problems:
        print("C6: в src/ найдены константы, зашитые под шаблон:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nВсе размеры, цвета и шрифты берутся из TemplateManifest "
            "(ARCHITECTURE.md §7.4, правило 4).",
            file=sys.stderr,
        )
        return 1
    print(f"OK  проверено файлов: {len(list(SRC.rglob('*.py')))}, шаблонных констант нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
