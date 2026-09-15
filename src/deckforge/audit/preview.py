"""pptx → png для VLM-аудита и превью в UI. Change (6) `template-preview-render`.

LibreOffice headless в отдельном образе с кириллическими шрифтами: без них подстановка
шрифта делает превью и, следовательно, весь VLM-аудит недостоверным (§15).
Батч-конвертация одной командой — бюджет 40 с (§12).
"""

from __future__ import annotations

from pathlib import Path


def render_previews(pptx_path: Path, out_dir: Path, dpi: int = 150) -> dict[str, Path]:
    raise NotImplementedError("change (6) template-preview-render")
