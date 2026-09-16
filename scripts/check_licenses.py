#!/usr/bin/env python3
"""CI-гейт C1/C2: лицензии Apache-2.0/MIT, LLM ≤ 35B, text-to-image ≤ 20B.

Падает с ненулевым кодом, если `configs/models.yaml` нарушает собственные constraints.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deckforge.config import CONFIGS_DIR
from deckforge.registry.models import load_models_registry


def main() -> int:
    # Проверяются все реестры: подсунуть дисквалифицирующую модель можно в любой из них.
    registries = sorted(CONFIGS_DIR.glob("models*.yaml"))
    violations: list[str] = []
    for path in registries:
        registry = load_models_registry(path, strict=False)
        violations += [f"{path.name}: {v}" for v in registry.violations()]
        if not violations:
            print(f"--- {path.name}")
            for name, spec in registry.models.items():
                active = f", активных {spec.params_active_b}B" if spec.params_active_b else ""
                print(
                    f"OK  {name:12} {spec.endpoint_model_id:34} "
                    f"{spec.license:12} {spec.params_total_b}B{active}"
                )
    if violations:
        print("НАРУШЕНИЯ ОГРАНИЧЕНИЙ ТЗ:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
