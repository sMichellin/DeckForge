"""Golden-схемы: контракт §4 не меняется молча.

`schemas/*.schema.json` коммитятся. Расхождение с моделями означает изменение контракта
между слоями — его нужно осознать и провести отдельным change, а не заметить на демо.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from gen_schemas import EXPORTED, dump, resolve


@pytest.mark.parametrize("name", sorted(EXPORTED))
def test_schema_file_matches_model(name: str) -> None:
    path = ROOT / "schemas" / f"{name}.schema.json"
    assert path.exists(), f"нет {path.name}: запустите scripts/gen_schemas.py"
    assert path.read_text(encoding="utf-8") == dump(resolve(EXPORTED[name])), (
        f"{path.name} разошёлся с моделью — перегенерируйте и осознайте изменение контракта"
    )


def test_slide_ir_schema_forbids_rgb_literals() -> None:
    """C6/ADR-002 закреплены в самой схеме, а не только в ревью."""
    schema = json.loads((ROOT / "schemas" / "slide_ir.schema.json").read_text(encoding="utf-8"))
    color_ref = schema["$defs"]["ColorRef"]
    assert "#" not in json.dumps(color_ref)
    assert set(color_ref["enum"]) >= {"accent1", "dk1", "lt1"}


def test_gen_schemas_is_idempotent() -> None:
    before = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "schemas").glob("*.json")}
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_schemas.py")],
        check=True,
        capture_output=True,
    )
    after = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "schemas").glob("*.json")}
    assert before == after
