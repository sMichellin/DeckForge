#!/usr/bin/env python3
"""Гейт образа LibreOffice: кириллица рисуется, а не подставляется.

Если нужных шрифтов в образе нет, LibreOffice **молча** подставит свои. Превью разойдётся
с тем, что увидит человек в PowerPoint, и весь VLM-аудит будет врать, не подавая признаков
неисправности (ARCHITECTURE.md §15). Поэтому проверка живёт отдельным гейтом и запускается
при сборке образа, а не «когда-нибудь руками».

Живёт в scripts/, а не в src/: здесь литеральные кегли по делу — документ синтетический
и от шаблона не зависит, а в src/ такие литералы запрещены гейтом C6.

    python scripts/check_cyrillic_render.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deckforge.rendering.soffice import SofficeRenderer, SofficeUnavailableError

PHRASE = "Съешь ещё этих мягких французских булок"

#: Сорок знаков кеглем 40 pt дают заметно больше тысячи тёмных пикселей.
#: Подстановка шрифта даёт либо пустоту, либо «квадратики» — и то и другое отличимо.
MIN_DARK_PIXELS = 1000


def render_phrase(renderer: SofficeRenderer, tmp: Path) -> Path:
    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Pt(36), Pt(36), Pt(600), Pt(120))
    box.text_frame.text = PHRASE
    box.text_frame.paragraphs[0].runs[0].font.size = Pt(40)

    source = tmp / "cyrillic.pptx"
    prs.save(str(source))
    pages = renderer.to_pngs(source, tmp / "out")
    if not pages:
        raise SofficeUnavailableError("конвертация не дала ни одной страницы")
    return pages[0]


def main() -> int:
    renderer = SofficeRenderer()
    if not renderer.available:
        print("LibreOffice или pdftoppm недоступны — гейт пропущен", file=sys.stderr)
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        try:
            page = render_phrase(renderer, Path(tmp))
        except Exception as exc:
            print(f"рендер не удался: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

        from PIL import Image

        image = Image.open(page).convert("L")
        dark = sum(1 for pixel in image.getdata() if pixel < 128)

    if dark < MIN_DARK_PIXELS:
        print(
            f"кириллица не отрисовалась: тёмных пикселей {dark} < {MIN_DARK_PIXELS}.\n"
            "Скорее всего, в образе нет шрифтов с кириллицей — превью и VLM-аудит "
            "будут врать, не показывая, что сломались.",
            file=sys.stderr,
        )
        return 1

    width, height = image.size
    print(f"OK  кириллица рисуется: тёмных пикселей {dark}, страница {width}×{height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
