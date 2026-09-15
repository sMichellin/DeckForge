"""Логотип, колонтитул и статичные фигуры мастера. Change (3) `template-parsing-core`.

Декор нужен аудиту `template.decor_moved`: чтобы заметить сдвинутый логотип, надо сначала
знать, где шаблон его держит.
"""

from __future__ import annotations

import hashlib

from lxml import etree

from deckforge.domain.base import BBox
from deckforge.domain.template import Decor, DecorElement, FooterSpec, StaticShape

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

#: Логотип — картинка в верхней или нижней полосе слайда, занимающая малую долю площади.
_LOGO_MAX_AREA_SHARE = 0.06
_LOGO_EDGE_BAND = 0.2


def _bbox(shape: etree._Element) -> BBox | None:
    off = shape.find(f".//{{{A}}}xfrm/{{{A}}}off")
    ext = shape.find(f".//{{{A}}}xfrm/{{{A}}}ext")
    if off is None or ext is None:
        return None
    try:
        cx, cy = int(ext.get("cx")), int(ext.get("cy"))
        if cx <= 0 or cy <= 0:
            return None
        return BBox(x=max(0, int(off.get("x"))), y=max(0, int(off.get("y"))), cx=cx, cy=cy)
    except (TypeError, ValueError):
        return None


def extract_decor(
    master_xml: bytes,
    master_id: str,
    slide_cx: int,
    slide_cy: int,
    media: dict[str, bytes] | None = None,
    rel_targets: dict[str, str] | None = None,
) -> Decor:
    """Разбор декоративного слоя мастера."""
    root = etree.fromstring(master_xml)
    slide_area = slide_cx * slide_cy
    media = media or {}
    rel_targets = rel_targets or {}

    logo: DecorElement | None = None
    static: list[StaticShape] = []

    for index, pic in enumerate(root.iter(f"{{{P}}}pic")):
        box = _bbox(pic)
        if box is None:
            continue

        blip = pic.find(f".//{{{A}}}blip")
        embed = blip.get(f"{{{R}}}embed") if blip is not None else None
        target = rel_targets.get(embed or "")
        blob = media.get(target or "")
        image_sha = f"sha256:{hashlib.sha256(blob).hexdigest()}" if blob else None

        near_edge = (
            box.y <= slide_cy * _LOGO_EDGE_BAND
            or box.bottom >= slide_cy * (1 - _LOGO_EDGE_BAND)
        )
        if logo is None and near_edge and box.area / slide_area <= _LOGO_MAX_AREA_SHARE:
            logo = DecorElement(
                layout_ids=[master_id],
                x=box.x,
                y=box.y,
                cx=box.cx,
                cy=box.cy,
                image_sha=image_sha,
            )
        else:
            static.append(StaticShape(shape_id=f"{master_id}-pic{index}", bbox=box, z=index))

    footer_ph = next(
        (
            shape
            for shape in root.iter(f"{{{P}}}sp")
            if (ph := shape.find(f".//{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")) is not None
            and ph.get("type") == "ftr"
        ),
        None,
    )
    footer_box = _bbox(footer_ph) if footer_ph is not None else None

    return Decor(
        logo=logo,
        footer=FooterSpec(
            present=footer_ph is not None,
            y_emu=footer_box.y if footer_box else None,
        ),
        static_shapes=static,
    )
