"""Границы слоёв (ARCHITECTURE.md §3) — машинная проверка, а не договорённость.

«Слой не импортирует слой выше себя» — если это только в документе, оно перестанет
выполняться на третий день спринта.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "deckforge"

# Порядок снизу вверх: каждый слой может импортировать только то, что левее него.
ORDER = [
    "domain",
    "registry",
    "inference",
    "parsing",
    "planning",
    "layout",
    "composition",
    "rendering",
    "audit",
    "export",
    "pipeline",
    "api",
]
RANK = {name: i for i, name in enumerate(ORDER)}


def layer_of(path: Path) -> str | None:
    rel = path.relative_to(SRC).parts
    return rel[0] if len(rel) > 1 and rel[0] in RANK else None


def imported_layers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
        elif isinstance(node, ast.Import):
            module = node.names[0].name
        if module and module.startswith("deckforge."):
            parts = module.split(".")
            if len(parts) > 1 and parts[1] in RANK:
                out.add(parts[1])
    return out


ALL_FILES = sorted(p for p in SRC.rglob("*.py") if layer_of(p))


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.relative_to(SRC).as_posix())
def test_layer_does_not_import_upwards(path: Path) -> None:
    layer = layer_of(path)
    assert layer is not None
    for imported in imported_layers(path):
        assert RANK[imported] <= RANK[layer], (
            f"{path.relative_to(SRC)}: слой {layer} импортирует {imported}, "
            "который выше него (ARCHITECTURE.md §3)"
        )


def test_domain_has_no_infrastructure_imports() -> None:
    """`domain` не знает ни про pptx, ни про сеть, ни про файловую систему."""
    forbidden = {"pptx", "lxml", "httpx", "openai", "langgraph", "fastapi", "redis", "boto3", "os"}
    for path in (SRC / "domain").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert name.split(".")[0] not in forbidden, f"{path.name}: импорт {name}"


def test_prompts_are_not_hardcoded_in_src() -> None:
    """C9: текст промпта в коде — нарушение требования ТЗ о внешних файлах."""
    markers = ("Ты — ", "Ты наполняешь", "Отвечай только", "systemprompt")
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if any(m in path.read_text(encoding="utf-8") for m in markers)
    ]
    assert offenders == [], f"промпты живут в prompts/, а не в коде: {offenders}"


def test_only_registry_reads_prompt_files() -> None:
    allowed = {"registry/prompts.py"}
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if ".j2" in path.read_text(encoding="utf-8")
        and path.relative_to(SRC).as_posix() not in allowed
        and "registry" not in path.relative_to(SRC).parts
    ]
    assert offenders == [], f"чтение промптов только через deckforge.registry: {offenders}"


def test_python_pptx_is_isolated_in_rendering() -> None:
    """§8.3: переход на форк power-pptx должен править один слой, а не весь репозиторий."""
    allowed_layers = {"rendering", "parsing", "audit", "export"}
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "pptx" in imported_top_levels(path) and layer_of(path) not in allowed_layers
    ]
    assert offenders == []


def imported_top_levels(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out
