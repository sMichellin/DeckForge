"""Превью готовой колоды для аудита и UI. Change (6) `template-preview-render`.

Нужны в двух местах: VLM-судья смотрит на слайд глазами (§5.2), а интерфейс показывает
находки поверх изображения. И то и другое требует, чтобы превью совпадало с тем, что
увидит человек в PowerPoint — отсюда требование к шрифтам в образе (§15).

Батч-конвертация одной командой: бюджет на вёрстку и рендер превью — 40 с (§12),
а запуск LibreOffice сам по себе стоит несколько секунд.
"""

from __future__ import annotations

from pathlib import Path

from deckforge.domain.slide import DeckIR
from deckforge.rendering.soffice import SofficeRenderer, SofficeUnavailableError

__all__ = ["SofficeUnavailableError", "render_deck_previews", "render_previews"]


def render_previews(pptx_path: Path, out_dir: Path, dpi: int = 150) -> dict[str, Path]:
    """Колода → png постранично. Ключ — номер слайда с единицы в виде строки."""
    renderer = SofficeRenderer(dpi=dpi)
    pages = renderer.to_pngs(pptx_path, out_dir)
    return {str(number): path for number, path in enumerate(pages, start=1)}


def render_deck_previews(
    pptx_path: Path, deck: DeckIR, out_dir: Path, dpi: int = 150
) -> dict[str, Path]:
    """То же, но ключом идёт `slide_id` из IR.

    Аудит оперирует `slide_id`, а не номерами страниц: после `split_slide` номера
    разъезжаются, и находка привязалась бы не к тому слайду.
    """
    pages = render_previews(pptx_path, out_dir, dpi=dpi)
    if len(pages) != len(deck.slides):
        raise SofficeUnavailableError(
            f"страниц {len(pages)}, а слайдов в IR {len(deck.slides)}: "
            "сопоставление находок с изображениями было бы неверным"
        )
    return {
        slide.slide_id: pages[str(number)]
        for number, slide in enumerate(deck.slides, start=1)
    }
