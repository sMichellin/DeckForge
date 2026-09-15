"""Граф генерации. Change (17) `pipeline-orchestration`.

    parse_template ─┐
                    ├─→ plan ─→ compose (fan-out по слайдам) ─→ fit ─→ render
    ingest_content ─┘                                                    │
                                                                         ▼
                                       export ←── accept ── HITL ←── audit
                                                             │
                                                             └── fix ──→ compose

Чекпойнты — sqlite: долгая задача переживает перезапуск, HITL прерывает граф на узле
`hitl` и возобновляет его после выбора пользователя.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_graph(checkpoint_path: Path | None = None) -> Any:
    raise NotImplementedError("change (17) pipeline-orchestration")
