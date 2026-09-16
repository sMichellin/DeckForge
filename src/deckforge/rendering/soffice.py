"""Конвертация через LibreOffice headless. Change (6) `template-preview-render`.

Живёт в слое `rendering`, потому что это работа с файлом презентации, а не аудит.
Слой `audit` пользуется этим через `audit.preview`.

Почему через pdf, а не сразу в png: `soffice --convert-to png` кладёт **только первый
слайд**. Колода конвертируется в pdf одной командой, страницы режутся `pdftoppm` —
это и быстрее батчем, и даёт постраничный результат.

Кириллица: если нужных шрифтов нет в системе, LibreOffice молча подставит свои,
превью разойдётся с PowerPoint и весь VLM-аудит будет врать (ARCHITECTURE.md §15).
Поэтому `check_cyrillic_support` — не диагностика, а часть контракта.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Бюджет на конвертацию колоды (§12: вёрстка и рендер превью — 40 с на всё).
DEFAULT_TIMEOUT_S = 180

#: Разрешение превью. 150 dpi хватает VLM, чтобы прочитать заголовок, и не раздувает
#: картинку: слайд 16:9 выходит примерно 1500×840.
DEFAULT_DPI = 150


class SofficeUnavailableError(RuntimeError):
    """LibreOffice не найден или не отработал.

    Отдельный тип, чтобы вызывающий мог деградировать на схематическое превью,
    а не падать посреди прогона.
    """


@dataclass(frozen=True, slots=True)
class SofficeRenderer:
    """Обёртка над headless-процессом."""

    binary: str = "soffice"
    timeout_s: int = DEFAULT_TIMEOUT_S
    dpi: int = DEFAULT_DPI

    @property
    def available(self) -> bool:
        return shutil.which(self.binary) is not None and shutil.which("pdftoppm") is not None

    def _require(self) -> None:
        if shutil.which(self.binary) is None:
            raise SofficeUnavailableError(
                f"не найден {self.binary!r}: нужен образ docker/Dockerfile.libreoffice"
            )
        if shutil.which("pdftoppm") is None:
            raise SofficeUnavailableError("не найден pdftoppm: поставьте poppler-utils")

    def to_pdf(self, source: Path, out_dir: Path) -> Path:
        """pptx → pdf. Та же команда используется экспортом в change (16)."""
        self._require()
        out_dir.mkdir(parents=True, exist_ok=True)

        # Профиль отдельный на каждый запуск: иначе параллельные вызовы дерутся за
        # ~/.config и второй молча не делает ничего.
        with tempfile.TemporaryDirectory() as profile:
            result = subprocess.run(
                [
                    self.binary,
                    "--headless",
                    "--norestore",
                    "--nolockcheck",
                    f"-env:UserInstallation=file://{profile}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(out_dir),
                    str(source),
                ],
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )

        pdf = out_dir / f"{source.stem}.pdf"
        if not pdf.exists():
            stderr = result.stderr.decode("utf-8", "replace")[:400]
            raise SofficeUnavailableError(f"конвертация {source.name} не дала pdf: {stderr}")
        return pdf

    def pdf_to_pngs(self, pdf: Path, out_dir: Path, prefix: str = "page") -> list[Path]:
        """pdf → по одному png на страницу, в порядке страниц."""
        self._require()
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(self.dpi), str(pdf), str(out_dir / prefix)],
            capture_output=True,
            timeout=self.timeout_s,
            check=True,
        )
        return sorted(out_dir.glob(f"{prefix}-*.png"))

    def to_pngs(self, source: Path, out_dir: Path) -> list[Path]:
        """pptx → png постранично. Одна конвертация на всю колоду (бюджет §12)."""
        pdf = self.to_pdf(source, out_dir)
        return self.pdf_to_pngs(pdf, out_dir, prefix=source.stem)
