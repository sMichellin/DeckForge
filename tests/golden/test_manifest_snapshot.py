"""Golden-снапшот манифеста. Change (3) `template-parsing-core`.

Ловит регрессии парсера: любое изменение того, что он извлекает, становится видимым
диффом, а не сюрпризом на демо. Обновляется осознанно: `UPDATE_GOLDEN=1 pytest`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from deckforge.parsing import TemplateParser
from tests.integration.synthetic_template import build

SNAPSHOT = Path(__file__).parent / "snapshots" / "synthetic_manifest.json"


def test_synthetic_manifest_matches_snapshot(tmp_path: Path) -> None:
    manifest = TemplateParser().parse(build(tmp_path / "synthetic.pptx"), use_cache=False)
    payload = manifest.model_dump(mode="json")
    # Хеш файла и имя зависят от временного каталога, снапшотить их бессмысленно.
    payload.pop("template_id")
    actual = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if os.environ.get("UPDATE_GOLDEN"):
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(actual, encoding="utf-8")

    assert SNAPSHOT.exists(), "снапшота нет: запустите UPDATE_GOLDEN=1 pytest"
    assert actual == SNAPSHOT.read_text(encoding="utf-8"), (
        "парсер стал извлекать из шаблона другое — осознайте изменение и обновите снапшот"
    )
