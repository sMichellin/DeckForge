#!/usr/bin/env python3
"""Гейт: у предложения есть дельта, у требования — сценарии, у change — тест.

Зачем. В OpenSpec шаг `/opsx:verify` («проверить, что реализация соответствует спекам»)
**не автоматизирован** — методология сама называет его опциональным и механики не даёт
(docs/concepts.md проекта Fission-AI/OpenSpec). У нас он не автоматизирован тоже,
и 26.09 это стоило дорого: правка RG43/RG44 была написана кодом и тестами **вперёд**
предложения, а красный тест, закреплённый на номере версии промпта, никто не поймал
до полного прогона.

Что проверяется — три вещи, каждая механическая:

1. у каждого незаархивированного change есть `proposal.md`;
2. если у change есть дельта, у каждого `### Requirement:` в ней есть хотя бы один
   `#### Scenario:` — требование без сценария непроверяемо, а «сценарии обязаны быть
   тестируемыми» — прямое правило OpenSpec;
3. change, который принёс код, назван хотя бы в одном тесте. Соглашение репозитория:
   тест называет свой change в докстринге модуля. Иначе доказательства у правки нет.

Чего гейт **не** проверяет и проверить не может: что сценарий и тест говорят об одном
и том же. Это работа ревью; гейт снимает только механическую часть.

Храповик. На 26.09 из 152 предложений 76 не названы ни одним тестом — это долг,
накопленный до гейта, и остановить им работу нельзя. Долг записан в `openspec/uncovered.txt`
и на красноту не влияет; **новое** предложение без теста гейт валит. Список может только
сокращаться: change, который обзавёлся тестом, гейт предлагает вычеркнуть.

    python scripts/lint_spec_coverage.py            # весь каталог, с храповиком
    python scripts/lint_spec_coverage.py --only <change>   # одна правка, без поблажек
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

#: Change'и, которые кодом не сопровождаются: зонтичные предложения и решения.
#: Список ведётся руками и объясняет каждое имя — молчаливого исключения быть не должно.
CODELESS = {
    "README.md": "оглавление каталога, а не change",
    "archive": "заархивированные change уже проверены",
}

REQUIREMENT = re.compile(r"^### Requirement:", re.M)
SCENARIO = re.compile(r"^#### Scenario:", re.M)


def _problems(changes: Path, tests: Path, debt: set[str]) -> tuple[list[str], list[str]]:
    """Замечания и долг: что валит гейт и что записано как накопленное до него."""
    found: list[str] = []
    owed: list[str] = []
    wanted = {c.name for c in changes.iterdir() if c.is_dir() and c.name not in CODELESS}
    named = _names_in_tests(tests, wanted)
    for change in sorted(changes.iterdir()):
        if change.name in CODELESS or not change.is_dir():
            continue
        proposal = change / "proposal.md"
        if not proposal.is_file():
            found.append(f"{change.name}: нет proposal.md — предложение не записано")
            continue
        found.extend(_delta_problems(change))
        if change.name not in named:
            line = (
                f"{change.name}: ни один тест не называет этот change — "
                "доказательства у правки нет"
            )
            (owed if change.name in debt else found).append(line)
        elif change.name in debt:
            owed.append(f"{change.name}: тест появился — вычеркнуть из openspec/uncovered.txt")
    return found, owed


def _delta_problems(change: Path) -> list[str]:
    """Требование без сценария непроверяемо: сценарий — это будущий тест."""
    found: list[str] = []
    for spec in sorted(change.glob("specs/*/spec.md")):
        text = spec.read_text(encoding="utf-8")
        blocks = REQUIREMENT.split(text)[1:]
        for block in blocks:
            title = block.splitlines()[0].strip()
            if not SCENARIO.search(block):
                found.append(
                    f"{change.name}/{spec.parent.name}: у требования «{title}» "
                    "нет ни одного сценария"
                )
    return found


def _names_in_tests(tests: Path, wanted: set[str]) -> set[str]:
    """Имена change'ей, названные в тестах: в тексте файла **или в его имени**.

    Первая версия искала кебаб-кейс из трёх и более слов и не видела `web-ui` вовсе.
    Вторая читала только текст — и не засчитывала тест
    `test_the_floor_shortens_instead_of_overflowing.py`, названный ровно как change,
    но не повторивший его имя в докстринге (PR #223). Имя файла — такое же
    доказательство связи, как строка в тексте, и требовать обоих незачем.

    Подчёркивания имени файла приводятся к дефисам: `test_a_b_c.py` → `a-b-c`.
    """
    haystack: list[str] = []
    for path in tests.rglob("test_*.py"):
        haystack.append(path.read_text(encoding="utf-8", errors="ignore"))
        haystack.append(path.stem.removeprefix("test_").replace("_", "-"))
    text = "\n".join(haystack)
    return {name for name in wanted if name in text}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changes", type=Path, default=Path("openspec/changes"))
    parser.add_argument("--tests", type=Path, default=Path("tests"))
    parser.add_argument(
        "--only",
        default=None,
        help="проверить один change по имени: без храповика, так гейт зовут в PR",
    )
    parser.add_argument(
        "--debt",
        type=Path,
        default=Path("openspec/uncovered.txt"),
        help="список предложений без теста, накопленный до гейта",
    )
    args = parser.parse_args(argv)

    debt: set[str] = set()
    if args.debt.is_file() and not args.only:
        debt = {
            line.split("#")[0].strip()
            for line in args.debt.read_text(encoding="utf-8").splitlines()
            if line.split("#")[0].strip()
        }

    problems, owed = _problems(args.changes, args.tests, debt)
    if args.only:
        problems = [
            line for line in problems if line.startswith(f"{args.only}:") or f"{args.only}/" in line
        ]
        owed = []

    for line in problems:
        print(f"  {line}")
    total = sum(1 for p in args.changes.iterdir() if p.is_dir() and p.name not in CODELESS)
    if owed:
        print(f"  долг до гейта: {len(owed)} предложений без теста (openspec/uncovered.txt)")
    if problems:
        print(f"НЕ ОК  предложений {total}, замечаний {len(problems)}")
        return 1
    print(f"OK  предложений {total}: у каждого есть proposal, сценарии и тест")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
