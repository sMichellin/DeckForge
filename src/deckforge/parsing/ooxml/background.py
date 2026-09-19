"""Фон макета: `p:bg` с каскадом slideLayout → slideMaster. Change (24).

Манифест до сих пор не описывал фон, и проверка контраста сравнивала текст со светлым
слотом темы. На шаблоне VK WorkSpace, где все макеты залиты `dk1`, заголовок цвета `dk1`
получал вердикт «норма»: контраст 1:1 считался как 21:1. Колода из двенадцати невидимых
заголовков прошла аудит без единой находки (19.09, прогон b8549ea89984).

Каскад OOXML для фона короче, чем для плейсхолдеров, и других ветвей у него нет:

1. `p:cSld/p:bg` самого макета — если задан, он и есть фон;
2. иначе `p:cSld/p:bg` мастера;
3. иначе фона нет нигде, и это отдельный ответ, а не светлый фон по умолчанию.

Поверх залитого фона шаблон часто кладёт картинку во весь слайд. Для читаемости текста
важна именно она, поэтому подложка ищется отдельно, а её цвет берётся усреднением пикселей:
точного ответа тут не существует, а средний ближе к правде, чем заливка, которую эта
картинка целиком закрывает.
"""

from __future__ import annotations

import io

from lxml import etree

from deckforge.domain.enums import ColorRef
from deckforge.domain.template import LayoutBackground, SlideSize, Theme

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

#: Слоты, которыми фон адресуется из макета. `bg1`/`tx1` — не цвета, а роли: настоящий
#: слот темы за ними указан в `p:clrMap` мастера, и у шаблонов он разный.
_MAPPED_SLOTS = frozenset({"bg1", "tx1", "bg2", "tx2"})

#: Доля стороны слайда, начиная с которой фигура закрывает фон, а не лежит на нём.
#: Значение то же, что у `audit.geometry.FULL_BLEED_SHARE`: дублируется, потому что
#: parsing не имеет права импортировать audit (ARCHITECTURE.md §3).
FULL_BLEED_SHARE = 0.95


def parse_color_map(master_xml: bytes) -> dict[str, str]:
    """`p:clrMap` мастера: роль → слот темы. Пусто, если мастер её не объявил."""
    root = etree.fromstring(master_xml)
    node = root.find(f"{{{P}}}clrMap")
    return {key: value for key, value in node.attrib.items()} if node is not None else {}


def _slot_of(value: str, color_map: dict[str, str]) -> ColorRef | None:
    """Слот темы по значению `schemeClr/@val` с учётом карты цветов мастера."""
    resolved = color_map.get(value, value) if value in _MAPPED_SLOTS else value
    # `folHlink` в схеме темы назван `folHlink`, а в ColorRef — так же; остальные совпадают.
    return next((ref for ref in ColorRef if ref.value == resolved), None)


def _fill_color(
    fill: etree._Element, color_map: dict[str, str]
) -> tuple[str | None, ColorRef | None]:
    """Цвет заливки: литерал и слот темы, если заливка задана ссылкой.

    Градиент сводится к первому упору: у фона важен не переход, а то, по чему читается
    текст, и брать для этого середину значило бы выдумывать цвет, которого в шаблоне нет.
    """
    srgb = fill.find(f".//{{{A}}}srgbClr")
    scheme = fill.find(f".//{{{A}}}schemeClr")
    if scheme is not None and scheme.get("val"):
        return None, _slot_of(scheme.get("val") or "", color_map)
    if srgb is not None and srgb.get("val"):
        return f"#{(srgb.get('val') or '').upper()}", None
    return None, None


def _background_of_part(
    part_xml: bytes, color_map: dict[str, str]
) -> tuple[str | None, ColorRef | None, bool] | None:
    """Фон одной части: литерал, слот темы, признак картинки. `None` — фон не задан."""
    root = etree.fromstring(part_xml)
    bg = root.find(f"{{{P}}}cSld/{{{P}}}bg")
    if bg is None:
        return None

    if bg.find(f".//{{{A}}}blipFill") is not None:
        # Картинка в самом `p:bg`: её байты лежат в связях части, и разрешает их
        # вызывающий — здесь известно только то, что заливка не цветная.
        return None, None, True

    for tag in ("solidFill", "gradFill", "pattFill"):
        fill = bg.find(f".//{{{A}}}{tag}")
        if fill is not None:
            hex_color, ref = _fill_color(fill, color_map)
            if hex_color or ref:
                return hex_color, ref, False

    # `p:bgRef` ссылается на стиль заливки темы по индексу; цвет при этом задан рядом.
    ref_node = bg.find(f"{{{P}}}bgRef")
    if ref_node is not None:
        hex_color, ref = _fill_color(ref_node, color_map)
        if hex_color or ref:
            return hex_color, ref, False
    return None


def full_bleed_blip(part_xml: bytes, slide_size: SlideSize) -> str | None:
    """`r:embed` картинки, закрывающей слайд целиком. Самая верхняя — она и видна.

    Возвращается идентификатор связи, а не байты: какой части он принадлежит, знает
    пакет, и разрешать связи внутри разбора одного XML было бы неправдой о том,
    кто чем владеет.
    """
    root = etree.fromstring(part_xml)
    found: list[tuple[int, str]] = []
    for index, pic in enumerate(root.iter(f"{{{P}}}pic")):
        ext = pic.find(f".//{{{A}}}xfrm/{{{A}}}ext")
        blip = pic.find(f".//{{{A}}}blip")
        if ext is None or blip is None:
            continue
        embed = blip.get(f"{{{R}}}embed")
        try:
            cx, cy = int(ext.get("cx")), int(ext.get("cy"))
        except (TypeError, ValueError):
            continue
        if not embed:
            continue
        wide = cx >= slide_size.cx_emu * FULL_BLEED_SHARE
        tall = cy >= slide_size.cy_emu * FULL_BLEED_SHARE
        if wide and tall:
            found.append((index, embed))
    return found[-1][1] if found else None


#: Сторона, до которой уменьшается подложка перед усреднением. Фон шаблона — это
#: фотография в несколько мегапикселей, а средний цвет от числа проб почти не зависит.
_SAMPLE_SIDE = 64


def average_color(image_bytes: bytes) -> str | None:
    """Средний цвет картинки в виде `#RRGGBB`. `None`, если её не прочитать.

    Прозрачные пиксели не учитываются: подложка с альфой усреднилась бы в чёрный,
    и белый текст на ней получил бы находку на ровном месте.
    """
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as image:
            rgba = image.convert("RGBA")
            if max(rgba.size) > _SAMPLE_SIDE:
                # Только ближайший сосед: любая интерполяция смешала бы прозрачные
                # пиксели с цветными, и отброшенная альфа вернулась бы в цвет.
                rgba = rgba.resize(
                    (_SAMPLE_SIDE, _SAMPLE_SIDE), Image.Resampling.NEAREST
                )
            raw = rgba.tobytes()
            opaque = [raw[i : i + 3] for i in range(0, len(raw), 4) if raw[i + 3]]
            if not opaque:
                return None
            channels = [sum(p[i] for p in opaque) // len(opaque) for i in range(3)]
            return "#" + "".join(f"{value:02X}" for value in channels)
    except Exception:
        # Битая или экзотическая картинка — не повод не разобрать шаблон: фон просто
        # останется тем, что под ней.
        return None


def parse_background(
    layout_xml: bytes,
    master_xml: bytes | None,
    theme: Theme,
    *,
    picture_bytes: bytes | None = None,
) -> LayoutBackground:
    """Фон макета как разрешённый цвет плюс сведения о том, откуда он взялся.

    `picture_bytes` — байты подложки во весь слайд, если вызывающий их нашёл
    (`full_bleed_blip` плюс связи части). Искать их здесь нельзя: связи знает пакет,
    а не разбор одного XML.
    """
    color_map = parse_color_map(master_xml) if master_xml else {}

    found = _background_of_part(layout_xml, color_map)
    source = "layout"
    if found is None and master_xml is not None:
        found = _background_of_part(master_xml, color_map)
        source = "master"

    hex_color, ref, is_image = found if found is not None else (None, None, False)
    if ref is not None:
        hex_color = theme.colors.get(ref)

    # Подложка во весь слайд закрывает заливку целиком: читается текст по ней.
    if picture_bytes is not None and (averaged := average_color(picture_bytes)) is not None:
        return LayoutBackground(
            color_hex=averaged, color_ref=None, source="picture", is_image=True
        )

    if hex_color is None:
        # Фона нет ни в макете, ни в мастере. Светлый слот темы — то же предположение,
        # что делает PowerPoint, и оно названо в `source`, а не выдано за факт шаблона.
        return LayoutBackground(
            color_hex=theme.colors.get(ColorRef.LT1),
            color_ref=ColorRef.LT1,
            source="theme",
            is_image=is_image,
        )
    return LayoutBackground(
        color_hex=hex_color, color_ref=ref, source=source, is_image=is_image
    )
