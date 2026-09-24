"""Дизайн-система объявлена в контрактах шагов, и у поля есть хозяин.

Change `design-system-in-the-skill-contracts`, таск RG9 (`docs/agents/tasks-24-09.md`).

Скиллы — объявленные контракты шагов графа: «промпт отвечает, что сказать модели, скилл —
как этот шаг встроен в граф» (`skills/registry.yaml`). Дизайн-системы в них не было нигде,
хотя в коде её отдаёт `parse` и читают `plan`, `compose`, `fit` и `render`. Контракт,
записанный только кодом узла, нечем проверить — и расхождение «поле принадлежит каталогу,
а спрашивают его у модели» прошло три PR'а и положило пять прогонов 24.09.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from deckforge.config import SKILLS_DIR, load_yaml
from deckforge.registry import get_prompt_registry, load_skill

ROOT = Path(__file__).resolve().parents[2]

#: Поля `SlideIR`, которые заполняет каталог композиций шаблона, а не модель.
CATALOGUE_FIELDS = {"recipe_id", "zone_id"}


def skill_names() -> list[str]:
    return sorted(load_yaml(SKILLS_DIR / "registry.yaml").get("skills") or {})


def test_the_template_analyst_declares_the_design_system() -> None:
    """Шаг, которому доступен файл, отдаёт не только манифест."""
    assert "design_system" in load_skill("template_analyst").outputs


@pytest.mark.parametrize("skill", ["deck_architect", "slide_designer"])
def test_the_steps_that_read_it_declare_it_as_an_input(skill: str) -> None:
    assert "design_system" in load_skill(skill).inputs


def test_the_catalogue_owns_the_recipe_and_the_zone() -> None:
    """У поля один хозяин на весь воркфлоу, и это объявлено, а не подразумевается."""
    assert set(load_skill("template_analyst").owns) >= CATALOGUE_FIELDS


def test_every_skill_declares_what_it_owns() -> None:
    """Пустой список — тоже объявление: «этот шаг особенным ничем не владеет»."""
    for name in skill_names():
        assert isinstance(load_skill(name).owns, list), name


def test_no_prompt_asks_the_model_for_a_field_with_an_owner() -> None:
    """То же, что проверяет гейт, — но в тестах, чтобы падало и без `make gates`."""
    owned = {field for name in skill_names() for field in load_skill(name).owns}
    for name in skill_names():
        spec = load_skill(name)
        if spec.prompt_ref is None:
            continue
        schema = get_prompt_registry().load(spec.prompt_ref).response_schema
        if schema is None:
            continue
        names = set(schema.get("properties") or {})
        for definition in (schema.get("$defs") or {}).values():
            names |= set(definition.get("properties") or {})
        assert not (names & owned), f"{name}: схема ответа просит {sorted(names & owned)}"


def test_the_gate_is_green_on_the_current_registry() -> None:
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lint_skill_contracts.py")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "OK" in done.stdout


def test_the_gate_catches_the_regression_it_was_written_for(tmp_path: Path) -> None:
    """Страховка гейта: на схеме, которая роняла прогоны, он обязан быть красным.

    Иначе гейт зелёный не потому, что контракты сошлись, а потому что он ничего не
    проверяет. Берётся схема `slide_composer@1.3.1` — та самая, что просила поля каталога.
    """
    import json

    schema = json.loads(
        (ROOT / "prompts" / "slide_composer" / "1.3.1" / "schema.json").read_text(encoding="utf-8")
    )
    names = set(schema.get("properties") or {})
    for definition in (schema.get("$defs") or {}).values():
        names |= set(definition.get("properties") or {})

    owned = set(load_skill("template_analyst").owns)
    assert names & owned, "1.3.1 больше не просит полей каталога — страховка потеряла смысл"
