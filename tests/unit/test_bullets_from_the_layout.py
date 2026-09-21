"""Маркер списка живёт в макете, а не только в мастере. Change `bullets-from-the-layout` (B11).

Прогон VK Education `6b1d9e82b612`: список в плейсхолдере вышел без маркеров. Причина
не в записи, а в разборе — `parse_bullets` читал только `p:txStyles/p:bodyStyle` мастера,
а все три шаблона кейса маркеров в мастере не объявляют вовсе. Знак задан в `lstStyle`
плейсхолдера макета, и задан так: первый уровень отключён (`buNone`), маркер начинается
со второго. На своих 55 слайдах-примерах VK Education ведёт себя ровно так же —
232 абзаца первого уровня без маркера и все 21 абзац второго со знаком.

Каскад здесь тот же, что применяет PowerPoint: уровень берётся из макета, если макет
о нём сказал, иначе из мастера. Список начинается с первого уровня, который шаблон
маркирует, — вместе со знаком он получает и вынос этого уровня.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from deckforge.domain.template import ThemeColors
from deckforge.parsing.ooxml.bullets import parse_bullets

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'

TEMPLATES = Path(__file__).resolve().parents[1] / "fixtures" / "templates"


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


def layout(*bodies: str) -> bytes:
    """Макет с телом-плейсхолдером: `lstStyle` внутри `p:txBody`, как в настоящем pptx."""
    shapes = "".join(
        "<p:sp><p:nvSpPr><p:nvPr><p:ph type='body' idx='1'/></p:nvPr></p:nvSpPr>"
        f"<p:txBody><a:lstStyle>{body}</a:lstStyle></p:txBody></p:sp>"
        for body in bodies
    )
    return (
        f"<p:sldLayout {P} {A}><p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:sldLayout>"
    ).encode()


VK_STYLE = (
    '<a:lvl1pPr><a:buNone/></a:lvl1pPr>'
    '<a:lvl2pPr marL="914400" indent="-317500"><a:buChar char="•"/></a:lvl2pPr>'
    '<a:lvl3pPr marL="1371600" indent="-304800"><a:buChar char="−"/></a:lvl3pPr>'
)


def test_marker_of_the_layout_is_found_when_the_master_is_silent() -> None:
    """Нарушитель B11: мастер молчит, и список оставался без маркера вовсе."""
    levels = parse_bullets(master(""), colors(), [layout(VK_STYLE)])

    assert [item.char for item in levels] == ["•", "−"], (
        "маркер объявлен в макете, а не в мастере — читать нужно оба"
    )


def test_list_starts_at_the_level_the_template_marks() -> None:
    """Отключённый первый уровень — решение автора: список идёт со второго, с его выносом."""
    levels = parse_bullets(master(""), colors(), [layout(VK_STYLE)])

    assert levels[0].char == "•"
    assert levels[0].margin_left_emu == 914400, "вынос взят у того уровня, что дал знак"
    assert levels[0].indent_emu == -317500


def test_the_layout_overrides_the_master_level_by_level() -> None:
    """«Шаблон 2024»: мастер даёт «•» на всех уровнях, макет гасит первый."""
    both = parse_bullets(
        master(
            '<a:lvl1pPr marL="180000" indent="-180000"><a:buChar char="•"/></a:lvl1pPr>'
            '<a:lvl2pPr marL="360000" indent="-180000"><a:buChar char="•"/></a:lvl2pPr>'
        ),
        colors(),
        [layout('<a:lvl1pPr><a:buNone/></a:lvl1pPr>')],
    )

    assert [item.char for item in both] == ["•"], "первый уровень погашен макетом"
    assert both[0].margin_left_emu == 360000, "остался второй уровень мастера"


def test_the_master_still_works_when_layouts_say_nothing() -> None:
    """Норма: шаблон со знаком в мастере разбирается как прежде."""
    levels = parse_bullets(
        master('<a:lvl1pPr marL="180000" indent="-180000"><a:buChar char="•"/></a:lvl1pPr>'),
        colors(),
        [layout("")],
    )

    assert [item.char for item in levels] == ["•"]


def test_a_template_silent_everywhere_stays_without_a_marker() -> None:
    """VK WorkSpace: знака нет ни в мастере, ни в макетах. Придумывать его нельзя."""
    assert parse_bullets(master(""), colors(), [layout(""), layout("")]) == []


def test_the_prevailing_style_wins_over_a_single_odd_layout() -> None:
    """У VK Tech 52 макета из 54 гасят первый уровень, два — нет. Правило берёт большинство."""
    odd = '<a:lvl1pPr marL="100000" indent="-100000"><a:buChar char="§"/></a:lvl1pPr>'
    levels = parse_bullets(
        master(""),
        colors(),
        [layout(VK_STYLE), layout(VK_STYLE), layout(VK_STYLE), layout(odd)],
    )

    assert levels[0].char == "•"


def test_layouts_without_a_body_placeholder_are_skipped() -> None:
    """Титульный макет без тела в голосовании не участвует и не обнуляет результат."""
    title_only = (
        f"<p:sldLayout {P} {A}><p:cSld><p:spTree>"
        "<p:sp><p:nvSpPr><p:nvPr><p:ph type='title' idx='0'/></p:nvPr></p:nvSpPr>"
        "<p:txBody><a:lstStyle><a:lvl1pPr><a:buNone/></a:lvl1pPr></a:lstStyle></p:txBody></p:sp>"
        "</p:spTree></p:cSld></p:sldLayout>"
    ).encode()

    levels = parse_bullets(master(""), colors(), [title_only, layout(VK_STYLE)])

    assert [item.char for item in levels] == ["•", "−"]


def test_broken_layout_xml_does_not_break_parsing() -> None:
    """Разбор шаблона не падает из-за одного нечитаемого макета."""
    levels = parse_bullets(master(""), colors(), [b"<not-xml", layout(VK_STYLE)])

    assert [item.char for item in levels] == ["•", "−"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Шаблон презентации VK Education.pptx", "•"),
        ("VK Tech шаблон.pptx", "•"),
        ("VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx", None),
    ],
)
def test_real_templates_of_the_case(name: str, expected: str | None) -> None:
    """Правило 10: проверка на настоящих шаблонах, а не только на собранном XML."""
    path = TEMPLATES / name
    if not path.is_file():
        pytest.skip("шаблон кейса в репозиторий не коммитится (.gitignore)")
    with zipfile.ZipFile(path) as pkg:
        masters = sorted(n for n in pkg.namelist() if n.startswith("ppt/slideMasters/slideMaster"))
        layouts = [
            pkg.read(n) for n in pkg.namelist()
            if n.startswith("ppt/slideLayouts/slideLayout") and n.endswith(".xml")
        ]
        levels = parse_bullets(pkg.read(masters[0]), colors(), layouts)

    if expected is None:
        assert levels == [], f"{name}: маркера нет нигде, и выдумывать его нельзя"
    else:
        assert levels and levels[0].char == expected, f"{name}: маркер не найден"
