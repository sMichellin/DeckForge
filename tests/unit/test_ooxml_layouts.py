"""Каскад slideMaster → slideLayout. Change (3) `template-parsing-core`."""

from __future__ import annotations

from deckforge.domain.enums import TextRole
from deckforge.domain.template import ShapeKind
from deckforge.parsing.ooxml.layouts import (
    parse_placeholders,
    parse_shapes,
    resolve_placeholders,
)

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


# --- фигуры вне плейсхолдеров -------------------------------------------------


def shape(x: int, y: int, cx: int, cy: int, *, tag: str = "sp", text: str = "") -> str:
    """Фигура БЕЗ плейсхолдера — то, чем шаблоны кладут фон и фотографии."""
    body = f"<p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody>" if text else ""
    return (
        f"<p:{tag}><p:nvSpPr><p:nvPr/></p:nvSpPr>"
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm></p:spPr>'
        f"{body}</p:{tag}>"
    )


SLIDE_CX, SLIDE_CY = 12_192_000, 6_858_000


def test_picture_without_a_placeholder_is_found() -> None:
    """Главный случай: в «Паттерн + фото» фотография лежит обычным p:pic.

    Без этого макет с фотографией на пол-слайда выглядит как пустой слайд с заголовком.
    """
    layout = part(
        sp('<p:ph type="title"/>', xfrm(600_000, 400_000, 3_000_000, 1_000_000)),
        shape(5_335_631, 0, 6_872_200, 6_855_356, tag="pic"),
    )
    shapes = parse_shapes(layout, SLIDE_CX, SLIDE_CY)
    assert [s.kind for s in shapes] == [ShapeKind.PICTURE]
    assert shapes[0].cx == 6_872_200


def test_placeholders_are_not_reported_as_shapes() -> None:
    """Иначе каждое место под контент посчиталось бы дважды."""
    layout = part(sp('<p:ph type="body" idx="1"/>', xfrm(1, 1, 9_000_000, 5_000_000)))
    assert parse_shapes(layout, SLIDE_CX, SLIDE_CY) == []


def test_decorative_text_shape_is_kept_with_its_text() -> None:
    """Гигантская кавычка в «Цитата без фото» — единственный признак, что это цитата."""
    layout = part(shape(544_512, 0, 2_058_988, 4_478_149, text="«"))
    (found,) = parse_shapes(layout, SLIDE_CX, SLIDE_CY)
    assert found.kind is ShapeKind.TEXT
    assert found.text == "«"


def test_shape_above_the_slide_is_clipped_not_dropped() -> None:
    """У декора координата бывает отрицательной; видимая часть — то, что читает человек."""
    layout = part(shape(500_000, 1, 2_000_000, 4_000_000))
    (found,) = parse_shapes(layout, SLIDE_CX, SLIDE_CY)
    assert found.y == 1


def test_tiny_decor_is_ignored() -> None:
    """Мелочь только зашумила бы схему и промпт."""
    layout = part(shape(0, 0, 40_000, 40_000))
    assert parse_shapes(layout, SLIDE_CX, SLIDE_CY) == []


def test_shapes_inside_groups_are_unwrapped() -> None:
    inner = shape(0, 0, 6_000_000, 6_000_000, tag="pic")
    layout = part(f"<p:grpSp><p:nvGrpSpPr/><p:grpSpPr/>{inner}</p:grpSp>")
    assert [s.kind for s in parse_shapes(layout, SLIDE_CX, SLIDE_CY)] == [ShapeKind.PICTURE]


def test_shape_without_geometry_is_skipped() -> None:
    layout = part("<p:sp><p:nvSpPr><p:nvPr/></p:nvSpPr><p:spPr/></p:sp>")
    assert parse_shapes(layout, SLIDE_CX, SLIDE_CY) == []


# --- гарнитура и кегль плейсхолдера (запрос потока B) ------------------------


def test_placeholder_carries_its_own_font_and_size() -> None:
    """Метрики текста считаются по гарнитуре **плейсхолдера**, а не роли целиком.

    Считать ширину по шрифту темы, когда плейсхолдер набран другим, значит полагаться
    на совпадение: на шаблонах кейса Arial и Play расходятся в пределах полупроцента,
    но на незнакомом шаблоне расхождение может быть любым (C6).
    """
    style = (
        '<a:lstStyle><a:lvl1pPr><a:defRPr sz="5400" b="1">'
        '<a:latin typeface="Play"/></a:defRPr></a:lvl1pPr></a:lstStyle>'
    )
    layout = part(
        f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
        f"<p:spPr>{xfrm(1, 2, 300, 400)}</p:spPr>"
        f"<p:txBody>{style}</p:txBody></p:sp>"
    )
    (placeholder,) = resolve_placeholders(layout, None)
    assert placeholder.font_family == "Play"
    assert placeholder.size_pt == 54.0
    assert placeholder.bold is True


def test_font_is_inherited_from_the_master() -> None:
    style = (
        '<a:lstStyle><a:lvl1pPr><a:defRPr sz="1800">'
        '<a:latin typeface="Inter"/></a:defRPr></a:lvl1pPr></a:lstStyle>'
    )
    master = part(
        f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
        f"<p:spPr>{xfrm(1, 2, 300, 400)}</p:spPr>"
        f"<p:txBody>{style}</p:txBody></p:sp>",
        root="sldMaster",
    )
    layout = part(sp('<p:ph type="body" idx="1"/>'))
    (placeholder,) = resolve_placeholders(layout, master)
    assert placeholder.font_family == "Inter"
    assert placeholder.size_pt == 18.0


def test_placeholder_without_declared_font_leaves_it_unset() -> None:
    """`None` честнее подстановки темы: вызывающий сам решит, чем заменять."""
    layout = part(sp('<p:ph type="title"/>', xfrm(1, 2, 300, 400)))
    (placeholder,) = resolve_placeholders(layout, None)
    assert placeholder.font_family is None


# --- txStyles мастера: последняя ступень каскада (правка 18.09) ----------------


def tx_styles(title: str = "", body: str = "", other: str = "") -> str:
    """`p:txStyles` мастера. Пустая строка — стиль не объявлен вовсе."""

    def style(name: str, size: str) -> str:
        if not size:
            return ""
        return (
            f"<p:{name}><a:lvl1pPr><a:defRPr {size}/></a:lvl1pPr></p:{name}>"
        )

    inner = style("titleStyle", title) + style("bodyStyle", body) + style("otherStyle", other)
    return f"<p:txStyles>{inner}</p:txStyles>" if inner else ""


def master_with_styles(*shapes: str, styles: str = "") -> bytes:
    tree = "".join(shapes)
    return (
        f"<p:sldMaster {NS}><p:cSld><p:spTree>{tree}</p:spTree></p:cSld>{styles}</p:sldMaster>"
    ).encode()


def test_text_styles_are_read_from_the_master() -> None:
    from deckforge.parsing.ooxml.layouts import parse_text_styles

    master = master_with_styles(styles=tx_styles(title='sz="3200" b="1"', body='sz="1400"'))
    styles = parse_text_styles(master)
    assert styles["titleStyle"][0] == 32.0
    assert styles["titleStyle"][1] is True
    assert styles["bodyStyle"][0] == 14.0


def test_master_without_text_styles_is_not_an_error() -> None:
    from deckforge.parsing.ooxml.layouts import parse_text_styles

    assert parse_text_styles(master_with_styles()) == {}


def test_size_falls_through_to_master_text_styles() -> None:
    """Шаблон, где кегль объявлен только в `txStyles`: без этой ступени он терялся.

    Так собран «Шаблон презентации 2024»: ни один из 34 макетов и ни одна фигура мастера
    размера заголовка не объявляют, и `size_pt` оставался пустым у всех.
    """
    master = master_with_styles(
        sp('<p:ph type="title" idx="0"/>', xfrm(1, 2, 300, 400)),
        styles=tx_styles(title='sz="3200"'),
    )
    layout = part(sp('<p:ph type="title" idx="0"/>'))
    (placeholder,) = resolve_placeholders(layout, master)
    assert placeholder.size_pt == 32.0


def test_shape_size_wins_over_text_styles() -> None:
    """`txStyles` — стиль по умолчанию и в каскаде OOXML стоит ниже фигуры."""
    master = master_with_styles(
        sp('<p:ph type="title" idx="0"/>', xfrm(1, 2, 300, 400), size='sz="4000"'),
        styles=tx_styles(title='sz="3200"'),
    )
    layout = part(sp('<p:ph type="title" idx="0"/>'))
    (placeholder,) = resolve_placeholders(layout, master)
    assert placeholder.size_pt == 40.0

    own = part(sp('<p:ph type="title" idx="0"/>', xfrm(1, 2, 3, 4), size='sz="2000"'))
    (placeholder,) = resolve_placeholders(own, master)
    assert placeholder.size_pt == 20.0


def test_body_placeholder_takes_body_style() -> None:
    """Стиль выбирается по типу плейсхолдера, а не один на всех."""
    master = master_with_styles(
        sp('<p:ph type="body" idx="1"/>', xfrm(1, 2, 300, 400)),
        styles=tx_styles(title='sz="3200"', body='sz="1400"'),
    )
    layout = part(sp('<p:ph type="body" idx="1"/>'))
    (placeholder,) = resolve_placeholders(layout, master)
    assert placeholder.size_pt == 14.0


def test_unknown_placeholder_type_takes_other_style() -> None:
    master = master_with_styles(
        sp('<p:ph type="sldNum" idx="4"/>', xfrm(1, 2, 300, 400)),
        styles=tx_styles(title='sz="3200"', other='sz="900"'),
    )
    layout = part(sp('<p:ph type="sldNum" idx="4"/>'))
    (placeholder,) = resolve_placeholders(layout, master)
    assert placeholder.size_pt == 9.0


CM = 360_000


def _band_layout(band_cy: int, band_size: str = 'sz="3200"', title: str = "") -> bytes:
    """Макет «Шаблона 2024»: полоса body 1,4 см кеглем 32 над телом 14 pt."""
    return part(
        title,
        sp('<p:ph type="body" idx="16"/>', xfrm(CM, CM, 23 * CM, band_cy), band_size),
        sp('<p:ph type="body" idx="21"/>', xfrm(CM, 5 * CM, 13 * CM, 11 * CM), 'sz="1400"'),
    )


def test_one_line_body_band_above_the_body_is_the_title() -> None:
    """ad29e1b6f77e: заголовок размечен body, и список уезжал в него восьмым кеглем."""
    specs = {spec.idx: spec for spec in resolve_placeholders(_band_layout(int(1.4 * CM)))}
    assert specs[16].role is TextRole.TITLE
    assert specs[16].ph_type == "BODY", "тип из XML не меняется — только роль"
    assert specs[21].role is TextRole.BODY


def test_tall_body_on_top_stays_body() -> None:
    """Высокий блок крупным кеглем — это тело, а не полоса заголовка."""
    specs = {spec.idx: spec for spec in resolve_placeholders(_band_layout(4 * CM))}
    assert specs[16].role is TextRole.BODY


def test_band_is_not_the_title_when_the_layout_has_one() -> None:
    title = sp('<p:ph type="title"/>', xfrm(CM, 0, 23 * CM, CM), 'sz="2400"')
    layout = _band_layout(int(1.4 * CM), title=title)
    specs = {spec.idx: spec for spec in resolve_placeholders(layout)}
    assert specs[16].role is TextRole.BODY
    assert specs[0].role is TextRole.TITLE


def test_band_in_a_smaller_size_than_the_body_stays_body() -> None:
    specs = {
        spec.idx: spec
        for spec in resolve_placeholders(_band_layout(int(0.8 * CM), band_size='sz="1200"'))
    }
    assert specs[16].role is TextRole.BODY
