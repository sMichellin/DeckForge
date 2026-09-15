"""Разбор темы. Change (4) `theme-extraction`.

Тесты идут на фрагментах XML, а не на файлах шаблонов: шаблоны организаторов —
их собственность и в репозиторий не кладутся, а разбирать надо не их, а стандарт.
"""

from __future__ import annotations

import pytest

from deckforge.domain.enums import ColorRef
from deckforge.parsing.ooxml.theme import nearest_color_ref, parse_theme

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'

SLOTS = ("dk1", "lt1", "dk2", "lt2", *[f"accent{i}" for i in range(1, 7)], "hlink", "folHlink")


def theme_xml(
    colors: dict[str, str] | None = None,
    *,
    major: str = "Montserrat",
    minor: str = "Inter",
    omit: str | None = None,
    sys_slot: str | None = None,
) -> bytes:
    values = dict.fromkeys(SLOTS, "123456")
    values.update(colors or {})
    parts = []
    for slot in SLOTS:
        if slot == omit:
            continue
        if slot == sys_slot:
            parts.append(f'<a:{slot}><a:sysClr val="windowText" lastClr="00FF00"/></a:{slot}>')
        else:
            parts.append(f'<a:{slot}><a:srgbClr val="{values[slot]}"/></a:{slot}>')
    return (
        f'<a:theme {A}><a:themeElements>'
        f'<a:clrScheme name="Проба">{"".join(parts)}</a:clrScheme>'
        f'<a:fontScheme name="Проба">'
        f'<a:majorFont><a:latin typeface="{major}"/><a:cs typeface=""/></a:majorFont>'
        f'<a:minorFont><a:latin typeface="{minor}"/><a:cs typeface="Noto"/></a:minorFont>'
        f"</a:fontScheme></a:themeElements></a:theme>"
    ).encode()


def test_all_twelve_slots_are_extracted() -> None:
    theme = parse_theme(theme_xml({"accent1": "E4002B", "dk1": "1a1a1a"}))
    assert theme.colors.accent1 == "#E4002B"
    assert theme.colors.dk1 == "#1A1A1A"
    assert len(theme.colors.model_dump()) == 12
    assert all(value.startswith("#") for value in theme.colors.model_dump().values())


def test_system_color_resolves_via_last_clr() -> None:
    """`sysClr` — обычный способ задать dk1; без `lastClr` цвет был бы потерян."""
    theme = parse_theme(theme_xml(sys_slot="dk1"))
    assert theme.colors.dk1 == "#00FF00"


def test_missing_slot_is_an_error_not_a_default() -> None:
    with pytest.raises(ValueError, match="accent3"):
        parse_theme(theme_xml(omit="accent3"))


def test_fonts_are_extracted_and_empty_cs_becomes_none() -> None:
    theme = parse_theme(theme_xml(major="Montserrat", minor="Inter"))
    assert (theme.fonts.major_latin, theme.fonts.minor_latin) == ("Montserrat", "Inter")
    assert theme.fonts.major_cs is None
    assert theme.fonts.minor_cs == "Noto"


def test_missing_latin_font_is_an_error() -> None:
    with pytest.raises(ValueError, match="латинские гарнитуры"):
        parse_theme(theme_xml(major=""))


def test_theme_without_colour_scheme_is_rejected() -> None:
    with pytest.raises(ValueError, match="clrScheme"):
        parse_theme(f"<a:theme {A}><a:themeElements/></a:theme>".encode())


def test_nearest_color_ref_finds_exact_and_approximate() -> None:
    theme = parse_theme(theme_xml({"accent1": "0077FF"}))
    ref, distance = nearest_color_ref("#0077FF", theme.colors)
    assert (ref, distance) == (ColorRef.ACCENT1, 0.0)

    ref, distance = nearest_color_ref("#0078FE", theme.colors)
    assert ref is ColorRef.ACCENT1 and 0 < distance < 5
