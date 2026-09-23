"""Слайды-примеры шаблона → `TemplateExample`. Change `design-system-from-examples` (DS1).

Дизайн-система шаблона живёт в его слайдах, а не в макетах: у трёх шаблонов кейса
от 87 % до 96 % содержимого примеров лежит вне плейсхолдеров — обычными фигурами поверх
почти пустого макета. Парсер их не открывал вовсе.

Отдельно проверяется масштаб группы. У VK Tech внутри групп стоят кегли 6,75 и 8,12 pt;
без пересчёта они выглядят ступенями типографской шкалы, хотя это группа уменьшена.
"""

from __future__ import annotations

import zipfile

import pytest

from deckforge.domain.template import ShapeKind, Theme, ThemeColors, ThemeFonts
from deckforge.parsing.ooxml.examples import parse_example
from tests.case_templates import case_template

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'

EMU_PER_PT = 12700


def theme() -> Theme:
    return Theme(
        colors=ThemeColors(
            dk1="#000000", lt1="#FFFFFF", dk2="#111111", lt2="#EEEEEE",
            accent1="#0077FF", accent2="#00E9FF", accent3="#FF0053", accent4="#2354D6",
            accent5="#4478FF", accent6="#FFD6E3", hlink="#0000EE", folHlink="#551A8B",
        ),
        fonts=ThemeFonts(major_latin="Play", minor_latin="Arial"),
    )


def slide(body: str) -> bytes:
    return (
        f"<p:sld {P} {A}><p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>"
    ).encode()


def textbox(x: int, y: int, cx: int, cy: int, text: str, *, size: int = 1800,
            typeface: str = "Play", ph: str = "") -> str:
    return (
        f"<p:sp><p:nvSpPr><p:nvPr>{ph}</p:nvPr></p:nvSpPr>"
        f"<p:spPr><a:xfrm><a:off x='{x}' y='{y}'/><a:ext cx='{cx}' cy='{cy}'/></a:xfrm></p:spPr>"
        f"<p:txBody><a:p><a:r><a:rPr sz='{size}'><a:latin typeface='{typeface}'/></a:rPr>"
        f"<a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>"
    )


def test_a_free_textbox_is_read_with_its_geometry() -> None:
    box = textbox(100000, 200000, 300000, 400000, "Тезис")
    example = parse_example(1, slide(box), None, theme())

    assert len(example.shapes) == 1
    shape = example.shapes[0]
    assert (shape.x, shape.y, shape.cx, shape.cy) == (100000, 200000, 300000, 400000)
    assert shape.kind is ShapeKind.TEXT
    assert shape.text_len == len("Тезис")
    assert shape.size_pt == 18.0
    assert shape.font_family == "Play"
    assert shape.placeholder_idx is None, "фигура вне плейсхолдера"


def test_a_shape_inside_a_scaled_group_is_brought_to_slide_coordinates() -> None:
    """Нарушитель: группа уменьшена вдвое, и кегль внутри неё — не ступень шкалы."""
    inner = textbox(1000, 1000, 2000, 2000, "Внутри", size=3600)
    group = (
        "<p:grpSp><p:nvGrpSpPr><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm>"
        "<a:off x='500000' y='600000'/><a:ext cx='1000' cy='1000'/>"
        "<a:chOff x='1000' y='1000'/><a:chExt cx='2000' cy='2000'/>"
        f"</a:xfrm></p:grpSpPr>{inner}</p:grpSp>"
    )

    example = parse_example(1, slide(group), None, theme())

    assert len(example.shapes) == 1
    shape = example.shapes[0]
    assert (shape.x, shape.y) == (500000, 600000), "начало группы не учтено"
    assert (shape.cx, shape.cy) == (1000, 1000), "масштаб группы не применён к размеру"
    assert shape.size_pt == 18.0, "кегль внутри группы не приведён к масштабу слайда"


def test_a_group_without_a_child_frame_keeps_the_child_as_is() -> None:
    """Группа без `chExt` масштаба не задаёт — пересчитывать нечего, а падать нельзя."""
    inner = textbox(1000, 1000, 2000, 2000, "Внутри")
    group = (
        "<p:grpSp><p:nvGrpSpPr><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>"
        f"{inner}</p:grpSp>"
    )

    example = parse_example(1, slide(group), None, theme())

    assert len(example.shapes) == 1
    assert example.shapes[0].size_pt == 18.0


def test_a_theme_font_reference_is_resolved() -> None:
    """`+mj-lt` — не гарнитура, а ссылка на мажорный шрифт темы."""
    example = parse_example(
        1, slide(textbox(0, 0, 100, 100, "Заголовок", typeface="+mj-lt")), None, theme()
    )

    assert example.shapes[0].font_family == "Play"


def test_a_picture_is_a_picture() -> None:
    pic = (
        "<p:pic><p:nvPicPr><p:nvPr/></p:nvPicPr><p:spPr><a:xfrm>"
        "<a:off x='0' y='0'/><a:ext cx='100' cy='100'/></a:xfrm></p:spPr></p:pic>"
    )
    example = parse_example(1, slide(pic), None, theme())

    assert example.shapes[0].kind is ShapeKind.PICTURE


def test_a_shape_without_geometry_is_skipped_not_fatal() -> None:
    """Фигура без `xfrm` наследует рамку плейсхолдера; для замера она бесполезна."""
    empty = "<p:sp><p:nvSpPr><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:p/></p:txBody></p:sp>"
    example = parse_example(1, slide(empty + textbox(0, 0, 10, 10, "Есть")), None, theme())

    assert [s.text_len for s in example.shapes] == [len("Есть")]


def test_an_empty_slide_gives_an_empty_example() -> None:
    example = parse_example(3, slide(""), None, theme())

    assert example.slide_index == 3
    assert example.shapes == []


def test_xml_id_is_read_from_cnvpr() -> None:
    """`cNvPr id` — настоящий id фигуры в XML; по нему фигура находится при копировании."""
    box = (
        "<p:sp><p:nvSpPr><p:cNvPr id='42' name='Тезис'/><p:nvPr/></p:nvSpPr>"
        "<p:spPr><a:xfrm><a:off x='0' y='0'/><a:ext cx='100' cy='100'/></a:xfrm></p:spPr>"
        "<p:txBody><a:p><a:r><a:t>Тезис</a:t></a:r></a:p></p:txBody></p:sp>"
    )
    example = parse_example(1, slide(box), None, theme())

    assert example.shapes[0].xml_id == 42


def test_xml_id_is_none_when_cnvpr_has_no_id() -> None:
    """Фигура без `cNvPr id` — xml_id остаётся None, а не падает."""
    box = textbox(0, 0, 100, 100, "Тезис")
    example = parse_example(1, slide(box), None, theme())

    assert example.shapes[0].xml_id is None


def test_part_name_is_passed_through() -> None:
    """`part_name` — имя части слайда-примера; по нему часть находится при копировании."""
    example = parse_example(1, slide(textbox(0, 0, 100, 100, "Тезис")), None, theme(),
                            part_name="ppt/slides/slide1.xml")

    assert example.part_name == "ppt/slides/slide1.xml"


def test_part_name_defaults_to_none() -> None:
    example = parse_example(1, slide(""), None, theme())

    assert example.part_name is None


# --- настоящие шаблоны (правило 10) ------------------------------------------


@pytest.mark.parametrize(
    ("name", "slides", "outside_share"),
    [
        ("VK Tech шаблон.pptx", 54, 0.90),
        ("VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx", 29, 0.85),
        ("Шаблон презентации VK Education.pptx", 55, 0.80),
    ],
)
def test_real_templates_are_read(name: str, slides: int, outside_share: float) -> None:
    """Замер из tasks-design-system: сколько примеров и какая доля вне плейсхолдеров."""
    import re

    with zipfile.ZipFile(case_template(name)) as pkg:
        parts = sorted(
            (n for n in pkg.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.findall(r"\d+", n)[-1]),
        )
        examples = [
            parse_example(index, pkg.read(part), None, theme())
            for index, part in enumerate(parts, start=1)
        ]

    assert len(examples) == slides, f"{name}: примеров не столько, сколько в замере"
    shapes = [shape for example in examples for shape in example.shapes]
    assert shapes, f"{name}: ни одной фигуры не разобрано"
    outside = [shape for shape in shapes if shape.placeholder_idx is None]
    assert len(outside) / len(shapes) >= outside_share, (
        f"{name}: доля содержимого вне плейсхолдеров ниже замера"
    )
