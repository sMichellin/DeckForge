"""Декор, который проверка защищает, — знак, а не подложка.
Change `decor-is-a-mark-not-a-backdrop` (задача C12).

Нарушитель: `template.decor_moved` давала 19 предупреждений из 35 на каждом прогоне
VK WorkSpace, и ни одного про логотип. Защищалась любая фигура макета, включая
фотографию под содержанием, а порог `tolerance_emu` (длина) сравнивался с площадью
пересечения в EMU² — то есть с нулём.

Норма здесь двойная: знак, накрытый блоком, находку по-прежнему даёт, а подложка
под содержанием и знак, задетый краем, — нет.
"""

from __future__ import annotations

from deckforge.audit.deterministic.template import decor_moved
from deckforge.domain.template import Decor, DecorElement, LayoutShape, ShapeKind, TemplateManifest
from tests.unit._audit_builders import body, cm, context_for, deck, slide, title

#: Область контента синтетического шаблона: поля 2 см по бокам и 1 см сверху и снизу.
MARGIN_CM = 2.0


def with_logo(manifest: TemplateManifest, *, at: tuple[float, float]) -> TemplateManifest:
    x, y = at
    logo = DecorElement(layout_ids=["M01"], x=cm(x), y=cm(y), cx=cm(1), cy=cm(0.5))
    return manifest.model_copy(update={"decor": Decor(logo=logo)})


def with_shape(
    manifest: TemplateManifest, *, box: tuple[float, float, float, float], shape_id: str = "s2"
) -> TemplateManifest:
    """Фигура макета `L07` — та самая «фон, фотографии, декор» из `LayoutSpec.shapes`."""
    x, y, width, height = box
    shape = LayoutShape(
        shape_id=shape_id,
        kind=ShapeKind.PICTURE,
        x=cm(x), y=cm(y), cx=cm(width), cy=cm(height),
    )
    layouts = [
        layout.model_copy(update={"shapes": [shape]}) if layout.layout_id == "L07" else layout
        for layout in manifest.layouts
    ]
    return manifest.model_copy(update={"layouts": layouts})


def findings(colony: object, manifest: TemplateManifest) -> list[str]:
    context = context_for("template.decor_moved", colony, manifest)
    return [f.evidence["decor"] for f in decor_moved(context)]


def test_a_block_over_the_logo_is_still_caught(manifest: TemplateManifest) -> None:
    """Нарушитель: логотип — знак по построению, и накрывать его нельзя нигде."""
    template = with_logo(manifest, at=(11, 6))
    colony = deck(slide(body("Поверх логотипа", box=(10.5, 5.8, 3, 1))))

    assert findings(colony, template) == ["логотип шаблона"]


def test_a_mark_the_template_keeps_in_the_margins_is_protected(
    manifest: TemplateManifest
) -> None:
    """Нарушитель: знак в полях шаблона накрыт блоком, ушедшим за поля."""
    template = with_shape(manifest, box=(0.2, 0.1, 1.5, 0.6))
    colony = deck(slide(body("Заехал в поля", box=(0.1, 0, 3, 1))))

    assert findings(colony, template) == ["декор макета s2"]


def test_a_backdrop_under_the_content_is_not_a_mark(manifest: TemplateManifest) -> None:
    """Норма: фигура внутри области контента — подложка под содержание, а не знак."""
    template = with_shape(manifest, box=(4, 4, 20, 10))
    colony = deck(slide(body("Текст на подложке", box=(4, 4, 20, 10))))

    assert findings(colony, template) == []


def test_a_mark_only_clipped_at_the_edge_is_not_covered(manifest: TemplateManifest) -> None:
    """Норма: «накрыл» — это скрыл, а не задел краем."""
    template = with_shape(manifest, box=(0.2, 0.1, 1.5, 0.6))
    colony = deck(slide(body("Краем", box=(1.5, 0, 3, 1))))

    assert findings(colony, template) == []


def test_a_block_in_a_placeholder_is_never_asked(manifest: TemplateManifest) -> None:
    """Норма (прежняя): положение блока в плейсхолдере выбрал автор шаблона."""
    template = with_logo(manifest, at=(MARGIN_CM, 5))

    assert findings(deck(slide(title(), body("Текст в плейсхолдере"))), template) == []
