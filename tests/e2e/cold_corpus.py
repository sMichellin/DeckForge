"""Источник холодных шаблонов для гейта C6.

Холодный шаблон — тот, который команда не открывала при разработке. Держать такой
в репозитории неудобно: шаблоны организаторов чужие и весят 13–33 МБ, а любой файл,
в который один раз заглянули ради отладки, холодным быть перестаёт (см. README рядом).

Поэтому корпус берётся из презентационных шаблонов, которые везёт с собой LibreOffice.
Они сделаны посторонними людьми, лежат в образе воркера, конвертируются в .pptx той же
командой, что и экспорт, и никем из нас не открывались. Конвертация кэшируется в tmp.

Приоритет у файлов, положенных в `cold/` руками: если там что-то есть, берутся они.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

COLD_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "templates" / "cold"

#: Куда LibreOffice кладёт свои презентационные шаблоны в образе воркера.
_LIBREOFFICE_TEMPLATES = Path("/usr/lib/libreoffice/share/template/common/presnt")

#: Конвертация занимает несколько секунд на файл, поэтому корпус берётся небольшой,
#: но разный по устройству: от одного макета до пяти, с разной типографикой.
_WANTED = ("DNA", "Focus", "Piano", "Portfolio")

_CACHE = Path(tempfile.gettempdir()) / "deckforge-cold-corpus"


def _manual() -> list[Path]:
    if not COLD_DIR.is_dir():
        return []
    return sorted(p for p in COLD_DIR.glob("*") if p.suffix.lower() in {".pptx", ".potx"})


def _from_libreoffice() -> list[Path]:
    """Конвертировать шаблоны LibreOffice в .pptx. Пусто, если офиса нет."""
    if shutil.which("soffice") is None or not _LIBREOFFICE_TEMPLATES.is_dir():
        return []

    _CACHE.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for name in _WANTED:
        source = _LIBREOFFICE_TEMPLATES / f"{name}.otp"
        target = _CACHE / f"{name}.pptx"
        if not source.exists():
            continue
        if not target.exists():
            with tempfile.TemporaryDirectory() as profile:
                subprocess.run(
                    [
                        "soffice", "--headless", "--norestore", "--nolockcheck",
                        f"-env:UserInstallation=file://{profile}",
                        "--convert-to", "pptx", "--outdir", str(_CACHE), str(source),
                    ],
                    capture_output=True,
                    timeout=180,
                    check=False,
                )
        if target.exists():
            out.append(target)
    return out


def cold_templates() -> list[Path]:
    """Холодные шаблоны: свои, если положены, иначе от LibreOffice."""
    return _manual() or _from_libreoffice()
