"""C6 как тест, а не только как CI-скрипт: константы шаблона в `src/` запрещены."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_lint_no_template_constants_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lint_no_template_constants.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_check_licenses_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_licenses.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
