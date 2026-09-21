"""Метрики оформления по отрисованному слайду. Change (15), задача C9.

Проверяется не вкус, а то, что метрика видит именно те дефекты, которых не видела
геометрия: содержание, прижатое к краю при формально заполненных рамках, и пустая
половина слайда, которую декор шаблона маскировал под содержание.
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw

from deckforge.audit.deterministic.design import (
    empty_zone,
    imbalance,
    ink_balance,
    ink_metrics,
)
from deckforge.audit.registry import CheckUnavailable
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import body, context_for, deck, slide, title

SIZE = (640, 360)

#: Совпадает с макетом слайда из `_audit_builders.slide`.
LAYOUT = "L07"


Box = tuple[int, int, int, int] | tuple[int, int, int, int, str]


def png(*boxes: Box) -> bytes:
    """Чёрный слайд с прямоугольниками — модель «чернил» на тёмном шаблоне.

    Пятый элемент — цвет: декор шаблона нарочно не белый. Белое по белому дало бы
    нулевую разницу, и текст поверх плашки исчезал бы при вычитании макета —
    чего на настоящем слайде не бывает, там текст контрастен подложке.
    """
    image = Image.new("RGB", SIZE, "black")
    painter = ImageDraw.Draw(image)
    for box in boxes:
        painter.rectangle(box[:4], fill=str(box[4]) if len(box) > 4 else "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def findings(
    previews: dict[str, bytes],
    manifest: TemplateManifest,
    layout_previews: dict[str, bytes] | None = None,
) -> list[Any]:
    colony = deck(slide(title(), body("Текст")))
    context = context_for(
        "design.ink_balance",
        colony,
        manifest,
        previews=previews,
        layout_previews=layout_previews,
    )
    return list(ink_balance(context))


# --------------------------------------------------------------- чернила и баланс


def test_content_pinned_to_the_top_is_found(manifest: TemplateManifest) -> None:
    """Прогон 693d464d54fb: смещение 0,29–0,44 на восьми слайдах из десяти.

    Рамки при этом были заполнены — геометрия молчала.
    """
    top = png((40, 20, 600, 70))
    _, dx, dy = ink_metrics(top)

    assert imbalance(dx, dy, 0.15, 0.15) > 1, f"смещение {dx:.2f}/{dy:.2f} — дефект не пойман"
    found = findings({"s01": top}, manifest)
    # Дефект один и тот же — пустота под прижатым к краю содержанием; назвать его можно
    # и зоной, и смещением, главное — назвать.
    assert len(found) == 1
    assert "прижато к краю" in found[0].message or "пустая зона" in found[0].message


def test_centred_content_passes(manifest: TemplateManifest) -> None:
    """После центрирования (#81) смещение живых колод — 0,04–0,20."""
    centred = png((40, 120, 600, 240))
    _, dx, dy = ink_metrics(centred)

    assert imbalance(dx, dy, 0.15, 0.15) <= 1
    assert findings({"s01": centred}, manifest) == []


def test_two_lines_of_large_figures_are_not_called_empty(manifest: TemplateManifest) -> None:
    """Показатели: чернил мало, но слайд держит поле композицией, а не массой текста."""
    kpi = png((60, 150, 200, 200), (260, 150, 400, 200), (450, 150, 590, 200))

    assert findings({"s01": kpi}, manifest) == []


def test_crowded_slide_is_found(manifest: TemplateManifest) -> None:
    """Свалка — тоже дефект: у живых колод чернил 1,9–8,6 %."""
    crowded = png(*[(x, y, x + 12, y + 12) for x in range(20, 620, 24)
                    for y in range(20, 340, 24)])
    ink, _, _ = ink_metrics(crowded)

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


# ------------------------------------------------- пустота в двух измерениях (C9)


def test_empty_half_is_found_though_every_row_is_busy(manifest: TemplateManifest) -> None:
    """Прогон f0b9ff6f0a74: правая половина пуста на семи слайдах из десяти.

    Каждая строка слайда при этом занята, поэтому метрика «самая высокая пустая
    строка» такого не видела вовсе.
    """
    left_half = png(*[(40, y, 280, y + 8) for y in range(30, 330, 20)])
    zone_w, zone_h = empty_zone(left_half)

    assert zone_w > 0.4, f"ширина пустой зоны {zone_w:.2f}"
    assert zone_h > 0.6, f"высота пустой зоны {zone_h:.2f}"


def test_text_across_the_slide_has_no_empty_zone(manifest: TemplateManifest) -> None:
    """Норма к тому же: воздух между строками — не дыра."""
    spread = png(*[(40, y, 600, y + 8) for y in range(30, 330, 20)])
    zone_w, zone_h = empty_zone(spread)

    assert min(zone_w, zone_h) <= 0.4, f"зона {zone_w:.2f}×{zone_h:.2f}"
    assert not any("пустая зона" in f.message for f in findings({"s01": spread}, manifest))


def test_air_over_a_row_of_figures_is_not_an_empty_zone(manifest: TemplateManifest) -> None:
    """Зона бывает широкой и низкой — это воздух над рядом показателей, а не дыра.

    Поэтому пределы по осям отдельные: один предел на площадь засчитывал бы находку
    любому слайду с содержанием в одну полосу по центру.
    """
    kpi = png((60, 150, 200, 210), (250, 150, 390, 210), (440, 150, 580, 210))
    zone_w, zone_h = empty_zone(kpi)

    assert zone_w > 0.4 and zone_h <= 0.4, f"зона {zone_w:.2f}×{zone_h:.2f}"
    assert findings({"s01": kpi}, manifest) == []


# --------------------------------------------------- допуски по осям, эллипс AeSlides


def test_sideways_shift_is_stricter_than_downwards() -> None:
    """AeSlides: x_tol 0,05 против y_tol 0,15 — колода читается сверху вниз.

    Содержание под заголовком естественно смещено вниз, а перекос вбок — дефект.
    """
    assert imbalance(0.1, 0.0, 0.05, 0.15) > 1
    assert imbalance(0.0, 0.1, 0.05, 0.15) <= 1


def test_the_tolerance_is_isotropic_without_a_layout_preview() -> None:
    """Без превью макета допуски равны: строгий по горизонтали ловил бы логотип шаблона.

    Пустой `x_tol` — это и есть «нечего вычитать»: норма возвращается к кругу,
    то есть к поведению до C9.
    """
    assert imbalance(0.1, 0.0, 0.0, 0.15) == imbalance(0.0, 0.1, 0.0, 0.15)


# ------------------------------------------- чернила содержания отдельно от шаблона (C9)


#: Оформление шаблона: плашка с узором во всю правую половину слайда. Так устроены
#: VK Tech и «Шаблон 2024» — справа плашка, слева место под текст. Узор здесь не
#: украшение теста: ровная заливка почти не даёт границ, а настоящий декор (логотип,
#: паттерн, плашка с подписью) даёт их столько же, сколько абзац текста, — на этом
#: метрика и слепла.
DECOR: tuple[Box, ...] = (
    (340, 20, 620, 340, "#4a4a4a"),
    *[
        (x, y, x + 22, y + 22, "#8c8c8c")
        for x in range(356, 600, 40)
        for y in range(36, 320, 40)
    ],
)


def chrome() -> bytes:
    return png(*DECOR)


def test_template_decor_does_not_hide_an_empty_half(manifest: TemplateManifest) -> None:
    """Задача C9. Прогон f0b9ff6f0a74: правая половина пуста на семи слайдах из десяти.

    Пока декор шаблона считается содержанием, правая половина выглядит занятой:
    без вычитания макета пустая зона — 50 × 3 % и находки нет вовсе.
    """
    on_the_left = png(*DECOR, *[(40, y, 300, y + 8) for y in range(40, 320, 24)])

    blind = findings({"s01": on_the_left}, manifest)
    seeing = findings({"s01": on_the_left}, manifest, {LAYOUT: chrome()})

    assert blind == [], "без вычитания макета декор шаблона маскирует пустую половину"
    assert [f for f in seeing if "пустая зона" in f.message], (
        f"с вычитанием макета дефект обязан находиться, найдено: {[f.message for f in seeing]}"
    )


def test_decor_no_longer_drags_the_centre_of_mass(manifest: TemplateManifest) -> None:
    """Обратная половина C9: замер на 1d0bc29cf23f s03 — центр тяжести 0,61 от логотипа.

    Показатели стоят ровно по центру, а декор справа тянет центр тяжести за собой,
    и проверка выдаёт находку на слайде без дефекта. Отчёт, который врёт на норме,
    учит себя не читать.
    """
    centred = png(*DECOR, (60, 150, 200, 210), (250, 150, 390, 210), (440, 150, 580, 210))

    blind = findings({"s01": centred}, manifest)
    seeing = findings({"s01": centred}, manifest, {LAYOUT: chrome()})

    assert [f for f in blind if "прижато к краю" in f.message], (
        "без вычитания макета ложная находка обязана воспроизводиться — иначе тест пуст"
    )
    assert seeing == [], f"на норме находок быть не должно: {[f.message for f in seeing]}"


def test_a_slide_that_added_nothing_is_not_called_balanced(manifest: TemplateManifest) -> None:
    """Слайд, совпавший с пустым макетом, — пустой слайд, а не ровно уравновешенный."""
    ink, _, _ = ink_metrics(chrome(), chrome())

    assert ink == 0.0
    found = findings({"s01": chrome()}, manifest, {LAYOUT: chrome()})
    assert len(found) == 1 and "почти пуст" in found[0].message


# ------------------------------------------- метрики по каждому слайду в отчёт (C7)


def test_metrics_are_reported_for_every_slide_not_only_for_violators() -> None:
    """C7. По находкам не видно, стала колода лучше или просто не дошла до порога."""
    from deckforge.audit.deterministic.design import slide_metrics

    values = slide_metrics(
        {"s01": png((40, 20, 600, 70)), "s02": png((40, 120, 600, 240))},
        {"s01": LAYOUT, "s02": LAYOUT},
    )

    assert set(values) == {"s01", "s02"}
    assert values["s01"]["imbalance"] > values["s02"]["imbalance"]
    assert all(item["chrome"] == 0.0 for item in values.values()), "макетов не давали"


def test_reported_metrics_subtract_the_layout_too() -> None:
    """Иначе отчёт и находка мерили бы одно разными линейками."""
    from deckforge.audit.deterministic.design import slide_metrics

    on_the_left = png(*DECOR, *[(40, y, 300, y + 8) for y in range(40, 320, 24)])
    blind = slide_metrics({"s01": on_the_left}, {"s01": LAYOUT})
    seeing = slide_metrics({"s01": on_the_left}, {"s01": LAYOUT}, {LAYOUT: chrome()})

    assert seeing["s01"]["zone_h"] > blind["s01"]["zone_h"]
    assert seeing["s01"]["chrome"] == 1.0
