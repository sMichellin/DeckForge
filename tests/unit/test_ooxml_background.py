"""Фон макета: каскад `p:bg`, карта цветов мастера, подложка во весь слайд. Change (24).

Проверка контраста до этой правки сравнивала текст со светлым слотом темы, потому что
фона в манифесте не было. На тёмном шаблоне такой вердикт всегда положительный: `dk1`
по `dk1` выходил 21:1. Здесь проверяется, что фон берётся из шаблона, а не назначается.
"""

from __future__ import annotations

import io

import pytest

from deckforge.domain.enums import ColorRef
from deckforge.domain.template import SlideSize, Theme, ThemeColors, ThemeFonts
from deckforge.parsing.ooxml.background import (
    average_color,
    full_bleed_blip,
    parse_background,
    parse_color_map,
)

NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)

SLIDE = SlideSize(cx_emu=12_192_000, cy_emu=6_858_000, aspect="16:9")


@pytest.fixture
def theme() -> Theme:
    """Тема нарочно не похожа на шаблоны организаторов: тест не должен знать их цвета (C6)."""
    return Theme(
        colors=ThemeColors(
            dk1="#101014",
            lt1="#FFFFFF",
            dk2="#3C4250",
            lt2="#EEF1F6",
            accent1="#2E6BE6",
            accent2="#12B886",
            accent3="#F59F00",
            accent4="#E03131",
            accent5="#7048E8",
            accent6="#0CA678",
            hlink="#1C7ED6",
            folHlink="#9775FA",
        ),
        fonts=ThemeFonts(major_latin="TestSans Display", minor_latin="TestSans Text"),
    )


def part(bg: str = "", tree: str = "", root: str = "sldLayout", extra: str = "") -> bytes:
    return (
        f"<p:{root} {NS}>{extra}<p:cSld>{bg}<p:spTree>{tree}</p:spTree></p:cSld></p:{root}>"
    ).encode()


def solid(fill: str) -> str:
    return f"<p:bg><p:bgPr><a:solidFill>{fill}</a:solidFill></p:bgPr></p:bg>"


def picture(cx: int, cy: int, embed: str = "rId9") -> str:
    return (
        f'<p:pic><p:blipFill><a:blip r:embed="{embed}"/></p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm></p:spPr>'
        "</p:pic>"
    )


def png(color: tuple[int, int, int], size: tuple[int, int] = (8, 8)) -> bytes:
    image_mod = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    image_mod.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_layout_fill_wins_over_master(theme: Theme) -> None:
    """Так устроен VK WorkSpace: мастер светлый, а все макеты залиты тёмным слотом."""
    layout = part(solid('<a:schemeClr val="dk1"/>'))
    master = part(solid('<a:schemeClr val="lt1"/>'), root="sldMaster")
    background = parse_background(layout, master, theme)
    assert background.color_ref is ColorRef.DK1
    assert background.color_hex == theme.colors.dk1
    assert background.source == "layout"


def test_master_fill_is_inherited_when_the_layout_is_silent(theme: Theme) -> None:
    layout = part()
    master = part(solid('<a:schemeClr val="lt1"/>'), root="sldMaster")
    background = parse_background(layout, master, theme)
    assert background.color_ref is ColorRef.LT1
    assert background.source == "master"


def test_color_map_of_the_master_is_applied(theme: Theme) -> None:
    """`bg1` — роль, а не цвет: за какой слот она отвечает, знает `p:clrMap` мастера."""
    layout = part(solid('<a:schemeClr val="bg1"/>'))
    master = part(
        root="sldMaster",
        extra='<p:clrMap bg1="dk2" tx1="lt1" bg2="dk1" tx2="lt2" accent1="accent1" '
        'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
        'accent6="accent6" hlink="hlink" folHlink="folHlink"/>',
    )
    background = parse_background(layout, master, theme)
    assert background.color_ref is ColorRef.DK2
    assert background.color_hex == theme.colors.dk2


def test_literal_fill_is_kept_as_is(theme: Theme) -> None:
    """Шаблон вправе залить фон литералом в обход темы — по нему и читается текст."""
    layout = part(solid('<a:srgbClr val="0c2d59"/>'))
    background = parse_background(layout, None, theme)
    assert (background.color_hex, background.color_ref) == ("#0C2D59", None)


def test_no_background_anywhere_is_named_as_an_assumption(theme: Theme) -> None:
    """Фона нет ни в макете, ни в мастере. Светлый слот — догадка, и она названа."""
    background = parse_background(part(), part(root="sldMaster"), theme)
    assert background.color_ref is ColorRef.LT1
    assert background.source == "theme"


def test_full_bleed_picture_becomes_the_background(theme: Theme) -> None:
    """Подложка во весь слайд закрывает заливку: читается текст по ней, а не по ней под."""
    layout = part(solid('<a:schemeClr val="lt1"/>'), tree=picture(SLIDE.cx_emu, SLIDE.cy_emu))
    background = parse_background(
        layout, None, theme, picture_bytes=png((12, 45, 89))
    )
    assert background.color_hex == "#0C2D59"
    assert background.source == "picture"
    assert background.is_image is True


def test_small_picture_is_not_a_background() -> None:
    """Декоративный знак в углу фоном не является, сколько бы их ни лежало на макете."""
    tree = picture(SLIDE.cx_emu // 4, SLIDE.cy_emu // 4)
    assert full_bleed_blip(part(tree=tree), SLIDE) is None


def test_full_bleed_picture_is_found_by_relationship_id() -> None:
    tree = picture(SLIDE.cx_emu, SLIDE.cy_emu, embed="rId7")
    assert full_bleed_blip(part(tree=tree), SLIDE) == "rId7"


def test_unreadable_picture_leaves_the_fill_in_place(theme: Theme) -> None:
    """Битая картинка — не повод не разобрать шаблон: фон остаётся тем, что под ней."""
    layout = part(solid('<a:schemeClr val="dk1"/>'), tree=picture(SLIDE.cx_emu, SLIDE.cy_emu))
    background = parse_background(layout, None, theme, picture_bytes=b"not an image")
    assert background.color_ref is ColorRef.DK1
    assert background.is_image is False


def test_average_color_ignores_transparent_pixels() -> None:
    """Подложка с альфой усреднилась бы в чёрный, и белый текст на ней получил бы находку."""
    image_mod = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    image = image_mod.new("RGBA", (4, 4), (255, 255, 255, 0))
    image.putpixel((0, 0), (200, 100, 50, 255))
    image.save(buffer, format="PNG")
    assert average_color(buffer.getvalue()) == "#C86432"


def test_color_map_is_optional() -> None:
    assert parse_color_map(part(root="sldMaster")) == {}
