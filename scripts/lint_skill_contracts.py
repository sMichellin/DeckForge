#!/usr/bin/env python3
"""Гейт контрактов скиллов: поле с хозяином у модели не спрашивают.

Каждый скилл объявляет в `owns` поля, которые заполняет его шаг. Если такое поле
стоит в схеме ответа промпта — у него два хозяина, и рано или поздно они разойдутся.

Так и вышло 24.09. `slide-recipes` отдал `recipe_id` и `zone_id` каталогу композиций
шаблона, но не убрал их из `response_omit` промпта `slide_composer`. Схема ответа их
потребовала, модель заполняла их выдумкой на каждом слайде, и на закрывающем — где
`bind_to_recipe` её не перезаписывал — выдумка доезжала до записи и роняла стадию
`render` с `KeyError`. Пять прогонов подряд, обнаружено через 138 секунд прогона.

Проверка дешёвая и идёт на каждом PR: расхождение контракта становится красным гейтом,
а не находкой на живом прогоне.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deckforge.config import SKILLS_DIR, load_yaml
from deckforge.registry import get_prompt_registry, load_skill


def property_names(schema: dict[str, Any]) -> set[str]:
    """Имена свойств схемы: и у корня, и у каждого вида блока в `$defs`."""
    names: set[str] = set(schema.get("properties") or {})
    for definition in (schema.get("$defs") or {}).values():
        names |= set(definition.get("properties") or {})
    return names


def main() -> int:
    registry = load_yaml(SKILLS_DIR / "registry.yaml").get("skills") or {}
    specs = {name: load_skill(name) for name in sorted(registry)}

    #: Хозяин у поля один на весь воркфлоу, поэтому и сверяется объединение: поле,
    #: которое заполняет разбор шаблона, нельзя спрашивать ни у одной модели.
    owner = {field: name for name, spec in specs.items() for field in spec.owns}
    problems: list[str] = []

    for name, spec in specs.items():
        if spec.prompt_ref is None:
            continue
        bundle = get_prompt_registry().load(spec.prompt_ref)
        if bundle.response_schema is None:
            continue
        asked = property_names(bundle.response_schema) & set(owner)
        for field in sorted(asked):
            problems.append(
                f"скилл {name} (промпт {bundle.ref}): схема ответа просит поле {field!r}, "
                f"которое заполняет {owner[field]}"
            )

    if problems:
        print("НАРУШЕНИЕ контрактов скиллов:")
        for line in problems:
            print(f"  - {line}")
        print(
            "\nПоле заполняет код — значит его место в `response_omit` промпта "
            "(`prompts/<skill>/<версия>/meta.yaml`), а не в схеме ответа."
        )
        return 1

    owned = sum(len(spec.owns) for spec in specs.values())
    asked_of_models = sum(1 for spec in specs.values() if spec.prompt_ref)
    print(
        f"OK  скиллов: {len(specs)}, полей с хозяином: {owned}, "
        f"схем ответа проверено: {asked_of_models}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
