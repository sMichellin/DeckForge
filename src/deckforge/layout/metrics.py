"""Метрики текста через `fontTools`. Change (12) `layout-fitting`.

Считаем **до** записи файла — это единственная защита от переполнения на чужих шрифтах (§15).

Ширины знаков берутся из `hmtx` настоящего файла гарнитуры (или пессимистичной замены,
см. `layout.fonts`). Кернинг не учитывается: он почти всегда сужает строку, так что без
него расчёт идёт с запасом.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from deckforge.domain.base import BBox
from deckforge.domain.units import EMU_PER_PT, TEXT_FRAME_INSET_X_EMU, TEXT_FRAME_INSET_Y_EMU
from deckforge.layout.fonts import FontLibrary, FontMetrics
from deckforge.layout.nonbreaking import bind as nonbreaking

#: Шаг строки при одинарном интерлиньяже в долях кегля. Правило формата, а не гарнитуры:
#: рендер LibreOffice дал ровно 1,2 и для Arial, и для DejaVu, и для Cambria Math,
#: у которой `winAscent + winDescent` в разы больше (см. proposal change 12).
LINE_HEIGHT_RATIO = 1.2

#: Допуск сравнения ширин в em: сумма float-ширин не должна переносить точно влезающее слово.
_EPS_EM = 1e-9

_PARAGRAPH_BREAK = re.compile(r"\r\n|[\n\r\v]")
#: Слово вместе с пробелами перед ним. Пробелы после последнего слова висят и места не занимают.
_SPACED_WORD = re.compile(r"( *)([^ ]+)")


@dataclass(frozen=True, slots=True)
class TextMetrics:
    width_emu: int
    height_emu: int
    lines: int
    #: Гарнитура, по которой фактически считалось.
    font_family: str
    #: `False` — шрифта шаблона нет, считали по пессимистичной замене.
    font_exact: bool
    #: Ширина самого длинного слова. Шире строки рамки — PowerPoint рвёт его по знакам
    #: («извлечен / ие»), и высота этого не видит: строк прибавилось, а места хватило.
    longest_word_emu: int = 0


@cache
def _default_library() -> FontLibrary:
    return FontLibrary.default()


def usable_width_emu(box: BBox) -> int:
    return max(0, box.cx - 2 * TEXT_FRAME_INSET_X_EMU)


def usable_height_emu(box: BBox) -> int:
    return max(0, box.cy - 2 * TEXT_FRAME_INSET_Y_EMU)


def line_height_emu(size_pt: float, line_spacing: float = 1.0) -> float:
    return LINE_HEIGHT_RATIO * size_pt * line_spacing * EMU_PER_PT


def split_paragraphs(text: str) -> list[str]:
    """Абзацы и разрывы строк: `<a:br/>` приходит вертикальной табуляцией.

    Неразрывные пробелы ставятся здесь же (Т4): замер обязан переносить строку там же,
    где её перенесёт PowerPoint, а писатель пишет текст через то же правило.
    """
    return [nonbreaking(part) for part in _PARAGRAPH_BREAK.split(text)] if text else []


def wrap_paragraph(paragraph: str, limit_em: float, metrics: FontMetrics) -> list[float]:
    """Переносит абзац по словам, как PowerPoint. Возвращает ширины строк в em.

    Пробелы на месте переноса и в конце абзаца висят за краем и ширины не занимают;
    пробелы внутри строки и в начале абзаца — занимают. Слово шире строки рвётся по знакам.
    """
    lines: list[float] = []

    def place(word: str, start_em: float) -> float:
        """Кладёт слово с позиции `start_em` новой строки, при нужде — по знакам."""
        width = start_em
        for ch in word:
            adv = metrics.advance_em(ch)
            if width > 0 and width + adv > limit_em + _EPS_EM:
                lines.append(width)
                width = 0.0
            width += adv
        return width

    current: float | None = None
    for match in _SPACED_WORD.finditer(paragraph):
        gap = metrics.text_width_em(match.group(1))
        word = match.group(2)
        word_em = metrics.text_width_em(word)
        if current is None:
            current = place(word, gap)
        elif current + gap + word_em <= limit_em + _EPS_EM:
            current += gap + word_em
        else:
            lines.append(current)
            current = place(word, 0.0)
    lines.append(current or 0.0)
    return lines


def _longest_word_em(paragraphs: list[str], metrics: FontMetrics) -> float:
    """Самое длинное слово в em. Граница слова — та же, что у переноса (`_SPACED_WORD`):
    неразрывный пробел — внутри слова."""
    return max(
        (
            metrics.text_width_em(match.group(2))
            for paragraph in paragraphs
            for match in _SPACED_WORD.finditer(paragraph)
        ),
        default=0.0,
    )


def longest_word_em(
    text: str,
    *,
    font_family: str,
    bold: bool = False,
    italic: bool = False,
    fonts: FontLibrary | None = None,
) -> float:
    """Ширина самого длинного слова в em — от кегля не зависит, поэтому меряется один раз,
    а не переносом всего текста на каждой ступени шкалы."""
    library = fonts if fonts is not None else _default_library()
    face = library.resolve(font_family, bold=bold, italic=italic).face
    return _longest_word_em(split_paragraphs(text), library.metrics(face))


def measure_text(
    text: str,
    *,
    font_family: str,
    size_pt: float,
    box: BBox,
    line_spacing: float = 1.0,
    bold: bool = False,
    italic: bool = False,
    fonts: FontLibrary | None = None,
) -> TextMetrics:
    """Сколько строк и места займёт текст в рамке `box` при данном кегле."""
    library = fonts if fonts is not None else _default_library()
    resolved = library.resolve(font_family, bold=bold, italic=italic)
    if not text:
        return TextMetrics(0, 0, 0, resolved.face.family, resolved.exact)

    metrics = library.metrics(resolved.face)
    emu_per_em = size_pt * EMU_PER_PT
    limit_em = usable_width_emu(box) / emu_per_em if emu_per_em > 0 else 0.0

    paragraphs = split_paragraphs(text)
    widths = [w for paragraph in paragraphs for w in wrap_paragraph(paragraph, limit_em, metrics)]
    longest = _longest_word_em(paragraphs, metrics)
    return TextMetrics(
        width_emu=round(max(widths) * emu_per_em),
        height_emu=round(len(widths) * line_height_emu(size_pt, line_spacing)),
        lines=len(widths),
        font_family=resolved.face.family,
        font_exact=resolved.exact,
        longest_word_emu=round(longest * emu_per_em),
    )
