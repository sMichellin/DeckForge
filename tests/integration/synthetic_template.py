"""Сборка синтетического .pptx-пакета для тестов парсера.

Шаблоны организаторов в репозиторий не кладутся: это их файлы, а публичный репозиторий
их распространять не должен. Да и проверять надо не конкретный шаблон, а соответствие
стандарту OOXML — поэтому пакет собирается здесь и специально не похож ни на один реальный.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"

SLIDE_CX, SLIDE_CY = 12_192_000, 6_858_000

SLOTS = (
    "dk1", "lt1", "dk2", "lt2",
    "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
    "hlink", "folHlink",
)
COLORS = {
    "dk1": "101014", "lt1": "FFFFFF", "dk2": "3C4250", "lt2": "EEF1F6",
    "accent1": "2E6BE6", "accent2": "12B886", "accent3": "F59F00",
    "accent4": "E03131", "accent5": "7048E8", "accent6": "0CA678",
    "hlink": "1C7ED6", "folHlink": "9775FA",
}


def _theme(major: str = "TestSans Display", minor: str = "TestSans Text") -> bytes:
    slots = "".join(f'<a:{s}><a:srgbClr val="{COLORS[s]}"/></a:{s}>' for s in SLOTS)
    return (
        f'<a:theme xmlns:a="{A}" name="Проба"><a:themeElements>'
        f'<a:clrScheme name="Проба">{slots}</a:clrScheme>'
        f'<a:fontScheme name="Проба">'
        f'<a:majorFont><a:latin typeface="{major}"/></a:majorFont>'
        f'<a:minorFont><a:latin typeface="{minor}"/></a:minorFont>'
        f"</a:fontScheme></a:themeElements></a:theme>"
    ).encode()


def _sp(ph: str, x: int, y: int, cx: int, cy: int, size_pt: float | None = None,
        bold: bool = False) -> str:
    style = (
        f'<a:lstStyle><a:lvl1pPr><a:defRPr sz="{int(size_pt * 100)}" b="{int(bold)}">'
        f'<a:solidFill><a:srgbClr val="{COLORS["dk1"]}"/></a:solidFill>'
        f"</a:defRPr></a:lvl1pPr></a:lstStyle>"
        if size_pt
        else "<a:lstStyle/>"
    )
    return (
        f"<p:sp><p:nvSpPr><p:cNvPr id=\"2\" name=\"ph\"/><p:nvPr>{ph}</p:nvPr></p:nvSpPr>"
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm></p:spPr>'
        f"<p:txBody><a:bodyPr/>{style}<a:p/></p:txBody></p:sp>"
    )


def _part(shapes: str, root: str, name: str = "") -> bytes:
    attr = f' name="{name}"' if name else ""
    return (
        f'<p:{root} xmlns:a="{A}" xmlns:p="{P}" xmlns:r="{R}">'
        f"<p:cSld{attr}><p:spTree>{shapes}</p:spTree></p:cSld>"
        f"</p:{root}>"
    ).encode()


def _rels(entries: list[tuple[str, str, str]]) -> bytes:
    body = "".join(
        f'<Relationship Id="{rid}" Type="{rtype}" Target="{target}"/>'
        for rid, rtype, target in entries
    )
    return f'<Relationships xmlns="{PKG}">{body}</Relationships>'.encode()


TITLE_PH = '<p:ph type="title"/>'
BODY_PH = '<p:ph type="body" idx="1"/>'
SUBTITLE_PH = '<p:ph type="subTitle" idx="1"/>'
FOOTER_PH = '<p:ph type="ftr" idx="11"/>'

MARGIN_X, MARGIN_Y = 700_000, 450_000
CONTENT_CX = SLIDE_CX - 2 * MARGIN_X


def build(path: Path, *, with_view_props: bool = False, empty_master: bool = False) -> Path:
    """Собрать пакет: один мастер, тема, три макета (титул, буллеты, две колонки)."""
    master_shapes = (
        ""
        if empty_master
        else _sp(TITLE_PH, MARGIN_X, MARGIN_Y, CONTENT_CX, 1_000_000, 40, bold=True)
        + _sp(BODY_PH, MARGIN_X, 1_800_000, CONTENT_CX, 4_000_000, 18)
        + _sp(FOOTER_PH, MARGIN_X, 6_300_000, 3_000_000, 250_000, 12)
    )

    layouts = {
        "slideLayout1.xml": (
            "Титул",
            _sp(TITLE_PH, MARGIN_X, 2_400_000, CONTENT_CX, 1_200_000, 40, bold=True)
            + _sp(SUBTITLE_PH, MARGIN_X, 3_800_000, CONTENT_CX, 700_000, 24),
        ),
        "slideLayout2.xml": (
            "Заголовок и содержимое",
            _sp(TITLE_PH, MARGIN_X, MARGIN_Y, CONTENT_CX, 1_000_000, 40, bold=True)
            + _sp(BODY_PH, MARGIN_X, 1_800_000, CONTENT_CX, 4_000_000, 18),
        ),
        "slideLayout3.xml": (
            "Две колонки",
            _sp(TITLE_PH, MARGIN_X, MARGIN_Y, CONTENT_CX, 1_000_000, 40, bold=True)
            + _sp(BODY_PH, MARGIN_X, 1_800_000, 5_200_000, 4_000_000, 18)
            + _sp('<p:ph type="body" idx="2"/>', 6_300_000, 1_800_000, 5_200_000, 4_000_000, 18),
        ),
    }

    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            _rels([("rId1", f"{R}/officeDocument", "ppt/presentation.xml")]).decode(),
        )

        master_ids = '<p:sldMasterIdLst><p:sldMasterId id="1" r:id="rId1"/></p:sldMasterIdLst>'
        z.writestr(
            "ppt/presentation.xml",
            f'<p:presentation xmlns:p="{P}" xmlns:r="{R}">{master_ids}'
            f'<p:sldSz cx="{SLIDE_CX}" cy="{SLIDE_CY}"/></p:presentation>',
        )
        z.writestr(
            "ppt/_rels/presentation.xml.rels",
            _rels([("rId1", f"{R}/slideMaster", "slideMasters/slideMaster1.xml")]).decode(),
        )

        z.writestr("ppt/theme/theme1.xml", _theme().decode())
        z.writestr(
            "ppt/slideMasters/slideMaster1.xml", _part(master_shapes, "sldMaster").decode()
        )
        z.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            _rels(
                [("rIdT", f"{R}/theme", "../theme/theme1.xml")]
                + [
                    (f"rId{i}", f"{R}/slideLayout", f"../slideLayouts/{name}")
                    for i, name in enumerate(layouts, start=1)
                ]
            ).decode(),
        )

        for name, (label, shapes) in layouts.items():
            z.writestr(f"ppt/slideLayouts/{name}", _part(shapes, "sldLayout", label).decode())

        if with_view_props:
            z.writestr(
                "ppt/viewProps.xml",
                f'<p:viewPr xmlns:p="{P}">'
                f'<p:guide pos="440"/><p:guide orient="horz" pos="284"/></p:viewPr>',
            )
    return path
