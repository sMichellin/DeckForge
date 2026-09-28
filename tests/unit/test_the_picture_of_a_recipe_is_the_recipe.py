"""Дубль слайдов по рецепту решается текстом.
Change `the-picture-of-a-recipe-is-the-recipe` (RG61).

В прогоне `96ef159` все 12 «дублей» на WorkSpace и VK Tech были слайдами на одном виде
рецепта с совпадением текста 0–25 %: перцептивный хеш слайда по рецепту меряет фон,
плашки и сетку карточек примера, то есть сам рецепт, а не содержание.

Превью здесь — одна и та же картинка у обоих слайдов: так выглядят два слайда на одном
рецепте для хеша.
"""

from __future__ import annotations

from deckforge.audit.deterministic.integrity import duplicate_slides
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import context_for, deck, slide, title
from tests.unit.test_audit_integrity import _png

CHECK = "integrity.duplicate_slides"
SAME = "Выручка выросла на треть за счёт одного канала"


def on_recipe(text: str, slide_id: str, recipe_id: str | None = "ex018"):  # type: ignore[no-untyped-def]
    return slide(title(text), slide_id=slide_id).model_copy(update={"recipe_id": recipe_id})


def found(manifest: TemplateManifest, *slides):  # type: ignore[no-untyped-def]
    picture = _png(1)
    context = context_for(
        CHECK, deck(*slides), manifest, previews={s.slide_id: picture for s in slides}
    )
    return list(duplicate_slides(context))


def test_one_recipe_different_text_is_not_a_duplicate(manifest: TemplateManifest) -> None:
    """Норма: картинка одна — это рецепт, а текст разный."""
    assert found(
        manifest,
        on_recipe("Выручка выросла на треть", "s02"),
        on_recipe("Затраты снизились вдвое", "s03"),
    ) == []


def test_one_recipe_same_text_is_a_duplicate(manifest: TemplateManifest) -> None:
    """Нарушитель: тот же рецепт и тот же текст — дубль, и сравнивался текст."""
    findings = found(manifest, on_recipe(SAME, "s02"), on_recipe(SAME, "s03"))

    assert [f.evidence["other_slide_id"] for f in findings] == ["s02"]
    assert findings[0].evidence["compared"] == "текст"


def test_slides_without_a_recipe_are_decided_by_the_picture(manifest: TemplateManifest) -> None:
    """Нарушитель прежнего правила: не по рецепту — решает картинка, как раньше."""
    findings = found(
        manifest,
        on_recipe("Выручка выросла на треть", "s01", recipe_id=None),
        on_recipe("Затраты снизились вдвое", "s02", recipe_id=None),
    )

    assert [f.evidence["compared"] for f in findings] == ["изображение"]
