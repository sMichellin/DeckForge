"""Каскад slideMaster → slideLayout. Change (3) `template-parsing-core`."""

from __future__ import annotations

from deckforge.domain.enums import TextRole
from deckforge.parsing.ooxml.layouts import parse_placeholders, resolve_placeholders

NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)


def sp(ph: str, xfrm: str = "", size: str = "") -> str:
    body = (
        f'<p:txBody><a:lstStyle><a:lvl1pPr><a:defRPr {size}/></a:lvl1pPr></a:lstStyle></p:txBody>'
        if size
        else "<p:txBody/>"
    )
    return (
        f"<p:sp><p:nvSpPr><p:nvPr>{ph}</p:nvPr></p:nvSpPr>"
        f"<p:spPr>{xfrm}</p:spPr>{body}</p:sp>"
    )


def xfrm(x: int, y: int, cx: int, cy: int) -> str:
    return f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'


def part(*shapes: str, root: str = "sldLayout") -> bytes:
    tree = "".join(shapes)
    return (
        f"<p:{root} {NS}><p:cSld><p:spTree>{tree}</p:spTree></p:cSld></p:{root}>"
    ).encode()


def test_geometry_is_inherited_from_master() -> None:
    master = part(sp('<p:ph type="body" idx="1"/>', xfrm(100, 200, 300, 400)), root="sldMaster")
    layout = part(sp('<p:ph type="body" idx="1"/>'))
    (placeholder,) = resolve_placeholders(layout, master)
    assert (placeholder.x, placeholder.y, placeholder.cx, placeholder.cy) == (100, 200, 300, 400)


def test_layout_geometry_overrides_master() -> None:
    master = part(sp('<p:ph type="body" idx="1"/>', xfrm(100, 200, 300, 400)), root="sldMaster")
    layout = part(sp('<p:ph type="body" idx="1"/>', xfrm(10, 20, 30, 40)))
    (placeholder,) = resolve_placeholders(layout, master)
    assert (placeholder.x, placeholder.cx) == (10, 30)


def test_empty_master_is_not_an_error() -> None:
    """Встречается в реальных шаблонах: мастер пуст, вся геометрия лежит в макетах."""
    layout = part(sp('<p:ph type="title"/>', xfrm(1, 2, 3, 4)))
    (placeholder,) = resolve_placeholders(layout, part(root="sldMaster"))
    assert placeholder.role is TextRole.TITLE
    assert placeholder.idx == 0, "титул без атрибута idx — это idx=0 по стандарту"


def test_placeholder_without_geometry_anywhere_is_dropped() -> None:
    """Выдумывать координаты нельзя: это ровно то, что запрещает C6."""
    layout = part(sp('<p:ph type="body" idx="1"/>'), sp('<p:ph type="title"/>', xfrm(1, 2, 3, 4)))
    resolved = resolve_placeholders(layout, part(root="sldMaster"))
    assert [p.ph_type for p in resolved] == ["TITLE"]


def test_zero_sized_placeholder_is_dropped() -> None:
    layout = part(sp('<p:ph type="body" idx="1"/>', xfrm(0, 0, 0, 0)))
    assert resolve_placeholders(layout, None) == []


def test_roles_are_mapped_from_standard_types_not_names() -> None:
    layout = part(
        sp('<p:ph type="ctrTitle"/>', xfrm(1, 1, 10, 10)),
        sp('<p:ph type="subTitle" idx="1"/>', xfrm(1, 20, 10, 10)),
        sp('<p:ph type="ftr" idx="11"/>', xfrm(1, 40, 10, 10)),
    )
    roles = {p.idx: p.role for p in resolve_placeholders(layout, None)}
    assert roles == {0: TextRole.TITLE, 1: TextRole.SUBTITLE, 11: TextRole.CAPTION}


def test_duplicate_idx_keeps_one_placeholder() -> None:
    """`SlideIR.placeholder_idx` обязан адресовать ровно один плейсхолдер."""
    layout = part(
        sp('<p:ph type="body" idx="1"/>', xfrm(1, 1, 10, 10)),
        sp('<p:ph type="body" idx="1"/>', xfrm(1, 50, 10, 10)),
    )
    assert len(resolve_placeholders(layout, None)) == 1


def test_sizes_are_read_from_layout_level_properties() -> None:
    layout = part(sp('<p:ph type="title"/>', xfrm(1, 1, 10, 10), size='sz="5400" b="1"'))
    (raw,) = parse_placeholders(layout)
    assert (raw.size_pt, raw.bold) == (54.0, True)
