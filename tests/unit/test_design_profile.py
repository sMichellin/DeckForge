"""Профиль оформления по примерам шаблона. Change `design-profile-from-examples` (DS7).

Метрики оформления не «хороши» и не «плохи» сами по себе: пустота на минималистичном
шаблоне — приём, на плотном — дефект. Сравнивать нужно с родными слайдами шаблона,
а не с числом из головы (arXiv:2508.19289, задача C8).

Изображения здесь рисуются, а не берутся из шаблона: юнит-тест не должен звать
LibreOffice. Проверка на настоящих примерах — в `proposal.md` замером.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from deckforge.audit.deterministic.design import metrics_of
from deckforge.audit.profile import MIN_EXAMPLES, Band, DesignProfile, profile_of

WIDTH, HEIGHT = 640, 360


def png(*, fill: float, offset: float = 0.0) -> bytes:
    """Слайд, у которого содержание занимает долю `fill` площади и смещено на `offset`."""
    image = Image.new("L", (WIDTH, HEIGHT), color=255)
    draw = ImageDraw.Draw(image)
    block_w = max(4, int(WIDTH * fill))
    left = int((WIDTH - block_w) / 2 + offset * WIDTH)
    # Полосы, а не сплошная заливка: метрика считает края, и у сплошного блока их два.
    for y in range(40, HEIGHT - 40, 16):
        draw.rectangle([left, y, left + block_w, y + 6], fill=40)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def native(count: int = 12) -> list[dict[str, float]]:
    """Родные слайды шаблона: похожие друг на друга, с небольшим разбросом."""
    return [metrics_of(png(fill=0.55 + (index % 3) * 0.02)) for index in range(count)]


def test_a_profile_describes_the_native_slides() -> None:
    profile = profile_of(native())

    assert profile.usable
    assert profile.examples == 12
    assert set(profile.bands) == {"ink", "imbalance", "zone_w", "zone_h"}
    assert profile.bands["ink"].median > 0


def test_a_native_looking_slide_stays_inside_the_profile() -> None:
    """Норма: слайд, похожий на примеры шаблона, находкой не становится."""
    profile = profile_of(native())

    deviations = profile.deviations(_metrics(png(fill=0.56)))

    assert max(deviations.values()) <= 1.0, f"свой слайд объявлен чужим: {deviations}"


def test_an_empty_slide_leaves_the_profile() -> None:
    """Нарушитель: слайд почти без содержания на фоне плотных примеров шаблона."""
    profile = profile_of(native())

    deviations = profile.deviations(_metrics(png(fill=0.04)))

    assert max(deviations.values()) > 1.0, f"пустой слайд не замечен: {deviations}"


def test_too_few_examples_give_no_profile() -> None:
    """Профиль из двух примеров — совпадение, а не профиль: проверка промолчит."""
    profile = profile_of(native(MIN_EXAMPLES - 1))

    assert not profile.usable
    assert profile.bands == {}


def test_no_examples_at_all_is_not_an_error() -> None:
    """Холодный шаблон без слайдов (правило 10)."""
    profile = profile_of([])

    assert not profile.usable
    assert profile.examples == 0


@pytest.mark.parametrize(
    ("value", "inside"),
    [(0.50, True), (0.52, True), (0.90, False), (0.10, False)],
)
def test_the_band_measures_in_spreads(value: float, inside: bool) -> None:
    band = Band(median=0.50, spread=0.04)

    assert (band.deviation(value) <= 1.0) is inside


def test_a_band_without_spread_compares_with_the_median() -> None:
    """Все примеры одинаковы: делить не на что, но и бесконечность возвращать нельзя."""
    band = Band(median=0.5, spread=0.0)

    assert band.deviation(0.5) == 0.0
    assert band.deviation(0.6) > 1.0


def test_a_profile_without_bands_reports_nothing() -> None:
    assert DesignProfile(bands={}, examples=0).deviations({"ink": 0.9}) == {}


def _metrics(page: bytes) -> dict[str, float]:
    return metrics_of(page)


# --- сама проверка ------------------------------------------------------------


def _findings(slide_png: bytes, examples: list[bytes], manifest: object) -> list[object]:
    from deckforge.audit.deterministic.design import unlike_the_template
    from tests.unit._audit_builders import body, context_for, deck, slide, title

    colony = deck(slide(title(), body("Текст")))
    context = context_for(
        "design.unlike_the_template",
        colony,
        manifest,
        previews={"s01": slide_png},
        example_previews=examples,
    )
    return list(unlike_the_template(context))


def _native_pages(count: int = 12) -> list[bytes]:
    return [png(fill=0.55 + (index % 3) * 0.02) for index in range(count)]


def test_the_check_reports_a_slide_unlike_the_template(manifest: object) -> None:
    """Нарушитель: пустой слайд там, где родные слайды шаблона плотные."""
    found = _findings(png(fill=0.04), _native_pages(), manifest)

    assert found, "слайд вне профиля шаблона не замечен"
    assert found[0].check_id == "design.unlike_the_template"
    assert "шаблона" in found[0].message


def test_the_check_stays_silent_on_a_native_looking_slide(manifest: object) -> None:
    """Норма: слайд в духе шаблона находкой не становится."""
    assert _findings(png(fill=0.56), _native_pages(), manifest) == []


def test_without_examples_the_check_is_skipped(manifest: object) -> None:
    """Холодный шаблон: профиля нет — проверка уходит в пропущенные, а не врёт."""
    from deckforge.audit.registry import CheckUnavailable

    with pytest.raises(CheckUnavailable):
        _findings(png(fill=0.04), [], manifest)
