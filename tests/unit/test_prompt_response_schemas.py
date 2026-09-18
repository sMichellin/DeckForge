"""Схема ответа модели выразима в строгом режиме провайдера.

Правка к change (11): композиция не запускалась вовсе — запрос отвергался **до модели**,
на проверке схемы. `SlideIR.fit_report` и `ChartBlock.axis_titles` — карты с произвольными
ключами, а строгий режим требует перечислить в `required` все ключи объекта.

Проверка идёт по форме схемы, а не по списку имён: новое поле `dict[str, X]` в доменной
модели обязано отсекаться само, иначе оно сломает композицию так же тихо, как эти два.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from deckforge.config import PROMPTS_DIR, load_yaml
from deckforge.domain.slide import SlideIR
from deckforge.inference.structured import strict_schema

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from gen_schemas import resolve, response_schema  # noqa: E402


def prompts_with_a_response_model() -> list[tuple[str, str, str]]:
    """`(скилл, версия, доменная модель)` по всем версиям всех промптов."""
    out = []
    for skill in sorted(p.name for p in PROMPTS_DIR.iterdir() if p.is_dir()):
        for version in sorted(p.name for p in (PROMPTS_DIR / skill).iterdir() if p.is_dir()):
            meta = load_yaml(PROMPTS_DIR / skill / version / "meta.yaml")
            if dotted := meta.get("response_model"):
                out.append((skill, version, dotted))
    return out


CASES = prompts_with_a_response_model()
IDS = [f"{skill}@{version}" for skill, version, _ in CASES]


def inexpressible(node: Any, path: str = "") -> list[str]:
    """Узлы, которые строгий режим не выражает: объект-карта без `properties`."""
    out: list[str] = []
    if isinstance(node, dict):
        if "properties" not in node and isinstance(node.get("additionalProperties"), dict):
            out.append(path or "/")
        for key, value in node.items():
            if key in ("properties", "$defs", "definitions", "patternProperties"):
                for name, sub in (value or {}).items():
                    out += inexpressible(sub, f"{path}/{key}/{name}")
            elif isinstance(value, dict):
                out += inexpressible(value, f"{path}/{key}")
            elif isinstance(value, list):
                for i, sub in enumerate(value):
                    out += inexpressible(sub, f"{path}/{key}/{i}")
    return out


@pytest.mark.parametrize(("skill", "version", "dotted"), CASES, ids=IDS)
def test_response_schema_survives_strict_mode(skill: str, version: str, dotted: str) -> None:
    schema = json.loads(
        (PROMPTS_DIR / skill / version / "schema.json").read_text(encoding="utf-8")
    )
    bad = inexpressible(strict_schema(schema))
    assert bad == [], (
        f"{skill}@{version}: строгий режим не выразит эти узлы, запрос отвергнут будет "
        f"до модели: {bad}"
    )


@pytest.mark.parametrize(("skill", "version", "dotted"), CASES, ids=IDS)
def test_committed_schema_matches_the_generator(skill: str, version: str, dotted: str) -> None:
    path = PROMPTS_DIR / skill / version / "schema.json"
    text, _ = response_schema(resolve(dotted))
    assert path.read_text(encoding="utf-8") == text, (
        f"{path.relative_to(ROOT)} разошёлся с моделью — перегенерируйте `make schemas`"
    )


def test_the_check_would_have_caught_the_original_bug() -> None:
    """Страховка от теста, который зелен потому, что ничего не проверяет.

    Доменная схема `SlideIR` невыразима — на ней проверка обязана сработать.
    """
    assert inexpressible(strict_schema(SlideIR.model_json_schema())) != []


def test_domain_contract_is_not_narrowed() -> None:
    """Сужается схема ответа, а не контракт между слоями: `fit_report` слой обязан принять."""
    contract = json.loads(
        (ROOT / "schemas" / "slide_ir.schema.json").read_text(encoding="utf-8")
    )
    assert "fit_report" in contract["properties"]


def test_dropped_fields_are_ones_the_model_never_had_to_send() -> None:
    """Выброшенные поля имеют значения по умолчанию, поэтому код композитора не меняется."""
    slide = SlideIR.model_validate(
        {
            "slide_id": "s01",
            "layout_id": "L07",
            "variant": "A",
            "blocks": [
                {
                    "block_id": "b1",
                    "type": "text",
                    "role": "body",
                    "text": "Выручка выросла на 37,5 %",
                }
            ],
        }
    )
    assert slide.fit_report == {}
