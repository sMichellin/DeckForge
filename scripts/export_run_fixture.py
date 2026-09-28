#!/usr/bin/env python3
"""Выгрузить готовый прогон фикстурой: план, IR, контент, манифест, дизайн-система, run.json.

План Б, change `the-deck-is-audited-offline` (6б). Потокам нужно мерить свою правку
на колодах настоящего прогона без модели и без стенда. Прогон оставил всё нужное
в чекпойнте; скрипт достаёт его оттуда и кладёт в `tests/fixtures/runs/`.

    python scripts/export_run_fixture.py artifacts/runs/<серия>/<run_id> \\
        --out tests/fixtures/runs/2026-09-28/vk-tech

Каталог прогона — как его кладёт стенд (`~/e2e-work/artifacts/runs/<run_id>/`):
`checkpoint.sqlite` рядом, `out/run.json` внутри.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deckforge.pipeline.replay import from_checkpoint, save_fixture


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("run_dir", type=Path, help="каталог прогона стенда")
    parser.add_argument("--out", type=Path, required=True, help="каталог фикстуры")
    parser.add_argument("--variant", default="A")
    args = parser.parse_args(argv)

    snapshot = from_checkpoint(args.run_dir, variant=args.variant)
    for path in save_fixture(snapshot, args.out):
        print(f"{path}  {path.stat().st_size:>9} байт")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
