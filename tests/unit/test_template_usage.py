"""Гарнитуры и цвета по фактическому набору. Change `design-system-from-examples` (DS2).

Тема называет гарнитуру, которой шаблон не пользуется: во всех трёх шаблонах кейса
в теме стоит Arial, а примеры набраны Play. Аудит сверяет шрифт колоды с темой и даёт
ложные находки (C3, C10) — ему нужен фактический набор, а не объявление.
"""

from __future__ import annotations

from deckforge.domain.enums import TextRole
from deckforge.domain.template import (
    ExampleShape,
    ShapeKind,
    TemplateExample,
    Theme,
    ThemeColors,
    ThemeFonts,
)
from deckforge.parsing.usage import collect_usage


def theme() -> Theme:
    return Theme(
        colors=ThemeColors(
            dk1="#000000", lt1="#FFFFFF", dk2="#111111", lt2="#EEEEEE",
            accent1="#0077FF", accent2="#00E9FF", accent3="#FF0053", accent4="#2354D6",
            accent5="#4478FF", accent6="#FFD6E3", hlink="#0000EE", folHlink="#551A8B",
        ),
        fonts=ThemeFonts(major_latin="Arial", minor_latin="Arial"),
    )


def shape(
    *, font: str | None = None, chars: int = 10, role: TextRole | None = None,
    color_hex: str | None = None, shape_id: str = "s",
) -> ExampleShape:
    return ExampleShape(
        shape_id=shape_id, kind=ShapeKind.TEXT, x=0, y=0, cx=10, cy=10,
        font_family=font, text_len=chars, role=role, color_hex=color_hex,
    )


def example(*shapes: ExampleShape) -> TemplateExample:
    return TemplateExample(slide_index=1, shapes=list(shapes))


def test_the_font_of_the_examples_beats_the_font_of_the_theme() -> None:
    """Нарушитель C3/C10: тема объявляет Arial, а набрано Play."""
    usage = collect_usage([example(shape(font="Play", chars=300))], [], theme())

    assert usage.knows_font("Play"), "гарнитура набора не попала в манифест"
    assert usage.fonts[0].family == "Play"
    assert usage.fonts[0].chars == 300


def test_shares_are_counted_over_all_characters() -> None:
    usage = collect_usage(
        [example(shape(font="Play", chars=300, shape_id="a"),
                 shape(font="Calibri", chars=100, shape_id="b"))],
        [], theme(),
    )

    shares = {font.family: round(font.share, 2) for font in usage.fonts if font.chars}
    assert shares == {"Play": 0.75, "Calibri": 0.25}
    assert sum(font.share for font in usage.fonts) == 1.0, "доли считаются от всех знаков"


def test_the_roles_of_a_font_are_remembered() -> None:
    """DS2 просит различать заголовки и тело: гарнитуры у них бывают разные."""
    usage = collect_usage(
        [example(shape(font="Play", role=TextRole.TITLE, shape_id="a"),
                 shape(font="Arial", role=TextRole.BODY, shape_id="b"))],
        [], theme(),
    )

    by_family = {font.family: font for font in usage.fonts}
    assert by_family["Play"].in_titles and not by_family["Play"].in_body
    assert by_family["Arial"].in_body and not by_family["Arial"].in_titles


def test_a_font_without_text_is_not_a_font_of_the_template() -> None:
    """Пустая надпись гарнитуру шаблона не подтверждает."""
    usage = collect_usage([example(shape(font="Comic Sans MS", chars=0))], [], theme())

    assert not usage.knows_font("Comic Sans MS")


def test_the_theme_fonts_are_known_even_without_examples() -> None:
    """Холодный шаблон без слайдов: гарнитуры темы известны всегда."""
    usage = collect_usage([], [], theme())

    assert usage.knows_font("Arial")


def test_a_literal_colour_becomes_a_palette_entry() -> None:
    """Фирменные цвета вне темы: у трёх шаблонов их 12–19 штук."""
    usage = collect_usage(
        [example(shape(color_hex="#EE5959", shape_id="a"),
                 shape(color_hex="#EE5959", shape_id="b"))],
        [], theme(),
    )

    assert len(usage.palette) == 1
    entry = usage.palette[0]
    assert entry.color_hex == "#EE5959"
    assert entry.count == 2
    assert entry.delta_e > 0
    assert entry.nearest_ref is not None


def test_the_palette_is_sorted_by_frequency() -> None:
    usage = collect_usage(
        [example(shape(color_hex="#EE5959", shape_id="a"),
                 shape(color_hex="#8F8F8F", shape_id="b"),
                 shape(color_hex="#8F8F8F", shape_id="c"))],
        [], theme(),
    )

    assert [entry.color_hex for entry in usage.palette] == ["#8F8F8F", "#EE5959"]


def test_fonts_of_the_layouts_count_too() -> None:
    """Шаблон без слайдов-примеров всё равно набран чем-то — плейсхолдерами макетов."""
    usage = collect_usage([], ["Play"], theme())

    assert usage.knows_font("Play")


# --- потребитель: аудит знает гарнитуры набора --------------------------------


def test_the_audit_knows_the_fonts_of_the_examples() -> None:
    """Без потребителя поле мертво: `template.font_not_in_theme` берёт набор отсюда."""
    from deckforge.audit.deterministic.template import template_fonts
    from deckforge.domain.template import FontUsage, TemplateManifest, TemplateUsage

    manifest = TemplateManifest.model_construct(
        theme=theme(),
        layouts=[],
        usage=TemplateUsage(fonts=[FontUsage(family="Play", chars=666, share=1.0)]),
    )

    known = template_fonts(manifest)

    assert "Play" in known, "гарнитура примеров осталась «чужой» для аудита"
    assert "Comic Sans MS" not in known, "чужая гарнитура должна оставаться находкой"
