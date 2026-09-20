"""Метрики оформления по отрисованному слайду. Change (15).

Проверяется не вкус, а то, что метрика видит именно тот дефект, которого не видела
геометрия: содержание, прижатое к краю при формально заполненных рамках.
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw

from deckforge.audit.deterministic.design import ink_balance, ink_metrics
from deckforge.audit.registry import CheckUnavailable
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import body, context_for, deck, slide, title

SIZE = (640, 360)


def png(*boxes: tuple[int, int, int, int]) -> bytes:
    """Чёрный слайд с белыми прямоугольниками — модель «чернил» на тёмном шаблоне."""
    image = Image.new("RGB", SIZE, "black")
    painter = ImageDraw.Draw(image)
    for box in boxes:
        painter.rectangle(box, fill="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def findings(previews: dict[str, bytes], manifest: TemplateManifest) -> list[Any]:
    colony = deck(slide(title(), body("Текст")))
    context = context_for("design.ink_balance", colony, manifest, previews=previews)
    return list(ink_balance(context))


def test_content_pinned_to_the_top_is_found(manifest: TemplateManifest) -> None:
    """Прогон 693d464d54fb: смещение 0,29–0,44 на восьми слайдах из десяти.

    Рамки при этом были заполнены — геометрия молчала.
    """
    top = png((40, 20, 600, 70))
    _, offset = ink_metrics(top)

    assert offset > 0.3, f"смещение {offset:.2f} — дефект не пойман"
    found = findings({"s01": top}, manifest)
    assert len(found) == 1 and "прижато к краю" in found[0].message


def test_centred_content_passes(manifest: TemplateManifest) -> None:
    """После центрирования (#81) смещение живых колод — 0,04–0,20."""
    centred = png((40, 120, 600, 240))
    _, offset = ink_metrics(centred)

    assert offset <= 0.3
    assert findings({"s01": centred}, manifest) == []


def test_two_lines_of_large_figures_are_not_called_empty(manifest: TemplateManifest) -> None:
    """Показатели: чернил мало, но слайд держит поле композицией, а не массой текста."""
    kpi = png((60, 150, 200, 200), (260, 150, 400, 200), (450, 150, 590, 200))

    assert findings({"s01": kpi}, manifest) == []


def test_crowded_slide_is_found(manifest: TemplateManifest) -> None:
    """Свалка — тоже дефект: у живых колод чернил 1,9–8,6 %."""
    crowded = png(*[(x, y, x + 12, y + 12) for x in range(20, 620, 24)
                    for y in range(20, 340, 24)])
    ink, _ = ink_metrics(crowded)

    assert ink > 0.15, f"чернил {ink:.1%}"
    found = findings({"s01": crowded}, manifest)
    assert len(found) == 1 and "перегружен" in found[0].message


def test_blank_slide_is_found(manifest: TemplateManifest) -> None:
    blank = png()
    found = findings({"s01": blank}, manifest)
    assert len(found) == 1 and "почти пуст" in found[0].message


def test_without_previews_the_check_is_skipped(manifest: TemplateManifest) -> None:
    """Проверка без картинки не догадывается, а честно уходит в пропущенные."""
    try:
        findings({}, manifest)
    except CheckUnavailable:
        return
    raise AssertionError("проверка молча прошла без превью")
