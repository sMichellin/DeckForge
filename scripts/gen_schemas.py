#!/usr/bin/env python3
"""Генерация JSON-схем из доменных моделей в `schemas/` и в `prompts/*/schema.json`.

Схемы — артефакт сборки, но коммитятся как golden-файлы: их расхождение с моделями
ловит `tests/golden/test_schemas.py` и означает несовместимое изменение контракта.
"""

from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path

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
            path.write_text(dump(resolve(dotted)), encoding="utf-8")
            written.append(path.relative_to(ROOT).as_posix())
        _ = entry

    for w in written:
        print(f"написано {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
