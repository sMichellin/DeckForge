"""Маркер списка из мастера шаблона. Change (4) `theme-extraction`.

Проверяется, что маркер именно извлекается, а не придумывается: шаблон без маркера
обязан остаться без маркера.
"""

from __future__ import annotations

from deckforge.domain.enums import ColorRef
from deckforge.domain.template import ThemeColors
from deckforge.parsing.ooxml.bullets import parse_bullet

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'


def colors() -> ThemeColors:
    return ThemeColors(
        dk1="#000000", lt1="#FFFFFF", dk2="#111111", lt2="#EEEEEE",
        accent1="#0077FF", accent2="#00E9FF", accent3="#FF0053", accent4="#2354D6",
        accent5="#4478FF", accent6="#FFD6E3", hlink="#0000EE", folHlink="#551A8B",
    )


def master(body: str) -> bytes:
    return (
        f"<p:sldMaster {P} {A}><p:txStyles><p:bodyStyle>{body}</p:bodyStyle>"
        "</p:txStyles></p:sldMaster>"
    ).encode()


def test_marker_is_taken_from_the_master_as_is() -> None:
    """Так устроен «Шаблон презентации 2024»: знак, гарнитура и цвет ссылкой на тему."""
    xml = master(
        '<a:lvl1pPr marL="180000" indent="-180000">'
        '<a:buClr><a:schemeClr val="accent6"/></a:buClr>'
        '<a:buFont typeface="Arial"/><a:buChar char="•"/></a:lvl1pPr>'
    )
    bullet = parse_bullet(xml, colors())

    assert bullet is not None
    assert (bullet.char, bullet.font) == ("•", "Arial")
    assert bullet.color_ref is ColorRef.ACCENT6
    assert (bullet.margin_left_emu, bullet.indent_emu) == (180000, -180000)


def test_template_without_a_marker_keeps_none() -> None:
    """У VK WorkSpace задана только гарнитура маркера: знака нет, и выдумывать его нельзя."""
    xml = master('<a:lvl1pPr><a:buClr><a:srgbClr val="000000"/></a:buClr>'
                 '<a:buFont typeface="Arial"/></a:lvl1pPr>')
    assert parse_bullet(xml, colors()) is None


def test_explicit_bunone_is_a_decision_not_a_gap() -> None:
    xml = master('<a:lvl1pPr><a:buNone/></a:lvl1pPr>')
    assert parse_bullet(xml, colors()) is None


def test_master_without_text_styles_is_not_an_error() -> None:
    assert parse_bullet(f"<p:sldMaster {P} {A}/>".encode(), colors()) is None


def test_literal_colour_becomes_a_theme_slot() -> None:
    """Цвет в IR — имя из темы, не #RRGGBB (правило 5 AGENTS.md)."""
    xml = master('<a:lvl1pPr><a:buClr><a:srgbClr val="0077FF"/></a:buClr>'
                 '<a:buChar char="—"/></a:lvl1pPr>')
    bullet = parse_bullet(xml, colors())

    assert bullet is not None and bullet.color_ref is ColorRef.ACCENT1


def test_levels_are_read_one_after_another() -> None:
    """Вложенный пункт со знаком первого уровня — список без уровней."""
    from deckforge.parsing.ooxml.bullets import parse_bullets

    xml = master(
        '<a:lvl1pPr marL="180000" indent="-180000"><a:buChar char="•"/></a:lvl1pPr>'
        '<a:lvl2pPr marL="360000" indent="-180000"><a:buChar char="–"/></a:lvl2pPr>'
    )
    levels = parse_bullets(xml, colors())

    assert [item.char for item in levels] == ["•", "–"]
    assert levels[1].margin_left_emu > levels[0].margin_left_emu


def test_reading_stops_at_the_first_level_the_template_skipped() -> None:
    """Дырку посередине писатель всё равно закрыл бы ближайшим уровнем сверху."""
    from deckforge.parsing.ooxml.bullets import parse_bullets

    xml = master(
        '<a:lvl1pPr><a:buChar char="•"/></a:lvl1pPr>'
        '<a:lvl2pPr><a:buNone/></a:lvl2pPr>'
        '<a:lvl3pPr><a:buChar char="»"/></a:lvl3pPr>'
    )
    assert [item.char for item in parse_bullets(xml, colors())] == ["•"]


def test_manifest_gives_the_nearest_declared_level() -> None:
    """Уровень, которого в шаблоне нет, наследует ближайший сверху — как в PowerPoint."""
    from deckforge.domain.template import BulletStyle, TemplateManifest

    manifest = TemplateManifest.model_construct(
        bullet_levels=[BulletStyle(char="•"), BulletStyle(char="–")]
    )

    assert manifest.bullet_for(0).char == "•"
    assert manifest.bullet_for(1).char == "–"
    assert manifest.bullet_for(5).char == "–", "глубокий уровень остался без маркера"
    assert TemplateManifest.model_construct(bullet_levels=[]).bullet_for(0) is None
