#!/usr/bin/env python3
"""CI-гейт C1/C2: лицензии Apache-2.0/MIT, LLM ≤ 35B, text-to-image ≤ 20B.

Падает с ненулевым кодом, если `configs/models.yaml` нарушает собственные constraints.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deckforge.registry.models import load_models_registry


def main() -> int:
    registry = load_models_registry(strict=False)
    violations = registry.violations()
    if violations:
        print("НАРУШЕНИЯ ОГРАНИЧЕНИЙ ТЗ:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    for name, spec in registry.models.items():
        active = f", активных {spec.params_active_b}B" if spec.params_active_b else ""
        print(f"OK  {name:12} {spec.hf_id:32} {spec.license:12} {spec.params_total_b}B{active}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
