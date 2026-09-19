#!/usr/bin/env python3
"""Генерация JSON-схем из доменных моделей в `schemas/` и в `prompts/*/schema.json`.

Схемы — артефакт сборки, но коммитятся как golden-файлы: их расхождение с моделями
ловит `tests/golden/test_schemas.py` и означает несовместимое изменение контракта.

**Схема ответа модели — не то же самое, что схема контракта.** В `schemas/` уезжает полный
дамп доменной модели: слой обязан уметь принять всё, что в ней объявлено. В `prompts/`
уезжает суженная схема — то, что модели разрешено прислать. Разница в одном: открытую карту
(`dict[str, X]`) строгий режим провайдера выразить не может, потому что требует перечислить
в `required` все ключи объекта, а у карты они произвольны. Такое свойство из схемы ответа
выбрасывается — и по делу: карты в наших моделях заполняются кодом, а не моделью
(`SlideIR.fit_report` считает слой `layout`, `ChartBlock.axis_titles` берутся из `Dataset`).

Второе сужение объявляет сам промпт: `response_omit` в `meta.yaml` — поля, которые модель
заполнять **не должна**. Без него поле остаётся в схеме, а строгий режим делает его
обязательным: промпт композитора запрещал координаты, схема требовала `x, y, cx, cy`,
и модель клала минимум, который пускала схема, — точку 0, 0, 1, 1 (прогон f4cf4257e07f).
"""

from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deckforge.config import PROMPTS_DIR, load_yaml

EXPORTED: dict[str, str] = {
    "template_manifest": "deckforge.domain.template.TemplateManifest",
    "content_package": "deckforge.domain.content.ContentPackage",
    "deck_plan": "deckforge.domain.plan.DeckPlan",
    "slide_ir": "deckforge.domain.slide.SlideIR",
    "deck_ir": "deckforge.domain.slide.DeckIR",
    "audit_report": "deckforge.domain.audit.AuditReport",
    "variant_profile": "deckforge.domain.variants.VariantProfile",
}


def resolve(dotted: str) -> type:
    module, _, name = dotted.rpartition(".")
    return getattr(import_module(module), name)  # type: ignore[no-any-return]


def dump(model: type) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"


def is_open_map(node: object) -> bool:
    """Свойство — карта с произвольными ключами, а не объект с фиксированным набором.

    Проверяется форма схемы, а не имя поля: невыразима в строгом режиме именно карта,
    и новое поле `dict[str, X]` обязано отсекаться само, без правки этого скрипта.
    """
    if not isinstance(node, dict):
        return False
    branches = node.get("anyOf") or node.get("oneOf") or [node]
    return any(
        isinstance(branch, dict)
        and "properties" not in branch
        and isinstance(branch.get("additionalProperties"), dict)
        for branch in branches
    )


def narrow(node: Any, dropped: set[str], omit: frozenset[str] = frozenset()) -> Any:
    """Убирает свойства-карты и поля из `omit` на любой глубине, включая `$defs`."""
    if isinstance(node, list):
        return [narrow(item, dropped, omit) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "properties" and isinstance(value, dict):
            kept = {}
            for name, sub in value.items():
                if is_open_map(sub) or name in omit:
                    dropped.add(name)
                    continue
                kept[name] = narrow(sub, dropped, omit)
            out[key] = kept
        else:
            out[key] = narrow(value, dropped, omit)

    # `required` чинится в том же узле, где выброшено свойство: строгий режим требует,
    # чтобы список и набор свойств совпадали, и осиротевшее имя отвергается наравне
    # с самой картой.
    if isinstance(out.get("properties"), dict) and isinstance(out.get("required"), list):
        out["required"] = [name for name in out["required"] if name in out["properties"]]
    return out


def response_schema(model: type, omit: frozenset[str] = frozenset()) -> tuple[str, set[str]]:
    """Схема ответа модели: доменная минус невыразимое в строгом режиме и минус `omit`."""
    dropped: set[str] = set()
    schema = narrow(model.model_json_schema(), dropped, omit)
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n", dropped


def main() -> int:
    out_dir = ROOT / "schemas"
    out_dir.mkdir(exist_ok=True)
    written = []
    for name, dotted in EXPORTED.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(dump(resolve(dotted)), encoding="utf-8")
        written.append(path.relative_to(ROOT).as_posix())

    # schema.json промптов, у которых объявлена response_model
    registry = load_yaml(PROMPTS_DIR / "registry.yaml").get("skills") or {}
    for skill, entry in registry.items():
        for version in sorted(p.name for p in (PROMPTS_DIR / skill).iterdir() if p.is_dir()):
            meta = load_yaml(PROMPTS_DIR / skill / version / "meta.yaml")
            dotted = meta.get("response_model")
            if not dotted:
                continue
            path = PROMPTS_DIR / skill / version / "schema.json"
            text, dropped = response_schema(
                resolve(dotted), frozenset(meta.get("response_omit") or ())
            )
            path.write_text(text, encoding="utf-8")
            note = f" (выброшено: {', '.join(sorted(dropped))})" if dropped else ""
            written.append(path.relative_to(ROOT).as_posix() + note)
        _ = entry

    for w in written:
        print(f"написано {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
