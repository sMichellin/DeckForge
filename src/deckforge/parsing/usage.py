"""Чем шаблон пользуется на самом деле. Change `design-system-from-examples` (DS2).

Тема — это объявление, а не факт. Во всех трёх шаблонах кейса тема называет Arial,
а примеры набраны Play: 666 фигур у VK Tech, 186 у VK WorkSpace, 110 у VK Education.
Аудит, который сверяет гарнитуру колоды с темой, на этом даёт ложные находки (C3, C10),
а отчёт с ложной находкой учит себя не читать.

То же с цветом. Фирменный `#0077FF` есть во всех трёх, но нейтральные серые и
дополнительные акценты живут только литералами на примерах — в двенадцать слотов темы
они не входят. Палитра остаётся **описанием** шаблона: в `SlideIR` литерал не попадает
никогда, правило 5 требует имя слота.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

from deckforge.domain.enums import TextRole
from deckforge.domain.template import (
    FontUsage,
    PaletteColor,
    TemplateExample,
    TemplateUsage,
    Theme,
)
from deckforge.parsing.ooxml.theme import nearest_color_ref

#: Роли, которые считаются заголовочными при учёте гарнитур.
_TITLE_ROLES = frozenset({TextRole.TITLE, TextRole.SUBTITLE})


def collect_usage(
    examples: Iterable[TemplateExample],
    layout_fonts: Sequence[str],
    theme: Theme,
) -> TemplateUsage:
    """Гарнитуры по числу набранных знаков и литеральная палитра примеров.

    Гарнитуры темы известны всегда, даже если шаблон без слайдов: ими набрана колода,
    которую мы соберём. Гарнитуры плейсхолдеров макетов — тоже набор шаблона, но знаков
    за ними не стоит, поэтому в долю они не входят.
    """
    chars: Counter[str] = Counter()
    titles: set[str] = set()
    body: set[str] = set()
    colors: Counter[str] = Counter()

    for example in examples:
        for shape in example.shapes:
            for literal in (shape.color_hex, shape.fill_hex):
                if literal:
                    colors[literal.upper()] += 1
            family = (shape.font_family or "").strip()
            if not family or shape.text_len <= 0:
                continue
            chars[family] += shape.text_len
            if shape.role in _TITLE_ROLES:
                titles.add(family)
            elif shape.role is not None:
                body.add(family)

    total = sum(chars.values())
    fonts = [
        FontUsage(
            family=family,
            chars=count,
            share=(count / total) if total else 0.0,
            in_titles=family in titles,
            in_body=family in body,
        )
        for family, count in chars.most_common()
    ]
    known = {font.family.strip().casefold() for font in fonts}
    for family in _declared(layout_fonts, theme):
        if family.strip().casefold() not in known:
            fonts.append(FontUsage(family=family, chars=0, share=0.0))
            known.add(family.strip().casefold())

    return TemplateUsage(fonts=fonts, palette=_palette(colors, theme))


def _declared(layout_fonts: Sequence[str], theme: Theme) -> list[str]:
    """Гарнитуры, которые шаблон называет сам: тема и плейсхолдеры его макетов."""
    declared = [
        theme.fonts.major_latin,
        theme.fonts.minor_latin,
        theme.fonts.major_cs,
        theme.fonts.minor_cs,
        *layout_fonts,
    ]
    return [family.strip() for family in declared if family and family.strip()]


def _palette(colors: Counter[str], theme: Theme) -> list[PaletteColor]:
    """Литеральные цвета по убыванию частоты, каждый — с ближайшим слотом темы."""
    palette: list[PaletteColor] = []
    for color_hex, count in colors.most_common():
        ref, delta = nearest_color_ref(color_hex, theme.colors)
        palette.append(
            PaletteColor(color_hex=color_hex, count=count, nearest_ref=ref, delta_e=delta)
        )
    return palette
