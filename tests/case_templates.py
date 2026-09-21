"""Шаблоны кейса для тестов, которые проверяют разбор на настоящих файлах (правило 10).

Сами шаблоны в репозиторий не коммитятся (`.gitignore`): в чекауте CI их нет. Тест,
который открывает их напрямую, на CI падает `FileNotFoundError` — так было в #121 и #127.
Через `case_template` он пропускается с понятной причиной, а на машине с шаблонами идёт.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent / "fixtures" / "templates"


def case_template(name: str) -> Path:
    """Путь к шаблону кейса; нет файла — тест пропускается, а не падает."""
    path = TEMPLATES / name
    if not path.is_file():
        pytest.skip(f"шаблон кейса «{name}» в репозиторий не коммитится (.gitignore)")
    return path
