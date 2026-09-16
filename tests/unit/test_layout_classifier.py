"""Классификатор макетов: эвристика плюс VLM. Change (5) `layout-classification`.

VLM здесь подделка: проверяется не качество модели, а механика — кого зовут, сколько раз,
что делают с разногласием и что происходит, когда модель молчит или врёт.
"""

from __future__ import annotations

from typing import Any

import pytest

from deckforge.domain.enums import LayoutKind, TextRole
from deckforge.domain.template import (
    LayoutCapacity,
    LayoutSpec,
    PlaceholderSpec,
    SlideSize,
)
from deckforge.parsing.layout_kind import (
    UNCERTAIN_BELOW,
    Classification,
    LayoutClassifier,
    geometry_signature,
)
from deckforge.parsing.layout_preview import SchematicPreview, describe_layout

SLIDE = SlideSize(cx_emu=12_192_000, cy_emu=6_858_000, aspect="16:9")


def ph(idx: int, ph_type: str, x: int, y: int, cx: int, cy: int,
       role: TextRole | None = None) -> PlaceholderSpec:
    return PlaceholderSpec(idx=idx, ph_type=ph_type, role=role, x=x, y=y, cx=cx, cy=cy)


def layout_of(*placeholders: PlaceholderSpec, name: str = "проба") -> LayoutSpec:
    return LayoutSpec(
        layout_id="L00",
        name=name,
        master="M01",
        index=0,
        kind=LayoutKind.CUSTOM,
        kind_confidence=0.0,
        kind_source="pending",
        capacity=LayoutCapacity(max_bullets=0, max_chars_body=0, max_chars_title=0),
        placeholders=list(placeholders),
    )


TITLE = ph(0, "TITLE", 600_000, 400_000, 10_900_000, 1_000_000, TextRole.TITLE)
BODY = ph(1, "BODY", 600_000, 1_800_000, 10_900_000, 4_000_000, TextRole.BODY)
#: Макет, на котором эвристика не уверена: заголовок и одна узкая полоска текста.
#: Это может быть и цитата, и подпись, и закрывающий слайд — геометрии мало.
NARROW = ph(1, "BODY", 600_000, 5_400_000, 10_900_000, 700_000, TextRole.BODY)
UNCERTAIN = layout_of(TITLE, NARROW)
#: Макет, на котором эвристика уверена и модель не нужна.
CONFIDENT = layout_of(TITLE, BODY)


class FakeVlm:
    """Отвечает по сценарию и считает вызовы."""

    def __init__(self, answers: list[Any]) -> None:
        self.answers = list(answers)
        self.calls = 0
        self.seeds: list[int] = []
        self.last_image: bytes | None = None

    def ask_image(self, *, system: str, user: str, image_png: bytes,
                  schema: dict[str, Any] | None = None, seed: int) -> dict[str, Any]:
        self.calls += 1
        self.seeds.append(seed)
        self.last_image = image_png
        answer = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


def verdict(kind: str) -> dict[str, str]:
    return {"kind": kind, "reason": "потому что"}


# --- маршрутизация -----------------------------------------------------------


def test_confident_heuristic_does_not_call_the_model() -> None:
    """Дорогой вызов делается только там, где без него не обойтись (§12)."""
    vlm = FakeVlm([verdict("chart")])
    classifier = LayoutClassifier(vlm=vlm)
    result = classifier.classify(CONFIDENT.placeholders, SLIDE, CONFIDENT)

    assert vlm.calls == 0
    assert result.source == "heuristic"
    assert result.kind is LayoutKind.BULLETS


def test_uncertain_heuristic_calls_the_model() -> None:
    vlm = FakeVlm([verdict("section")])
    classifier = LayoutClassifier(vlm=vlm, votes=3)
    result = classifier.classify(UNCERTAIN.placeholders, SLIDE, UNCERTAIN)

    assert vlm.calls == 3, "мажоритарное голосование — три прогона"
    assert len(set(vlm.seeds)) == 3, "прогоны должны идти с разными seed"
    assert result.kind is LayoutKind.SECTION
    assert result.source == "vlm"


def test_without_a_client_everything_stays_heuristic() -> None:
    classifier = LayoutClassifier()
    assert not classifier.enabled
    result = classifier.classify(UNCERTAIN.placeholders, SLIDE, UNCERTAIN)
    assert result.source == "heuristic"


# --- согласие и разногласие --------------------------------------------------


def test_agreement_raises_confidence_above_the_heuristic() -> None:
    vlm = FakeVlm([verdict("quote")])
    classifier = LayoutClassifier(vlm=vlm)
    heuristic_only = LayoutClassifier().classify(UNCERTAIN.placeholders, SLIDE, UNCERTAIN)
    result = classifier.classify(UNCERTAIN.placeholders, SLIDE, UNCERTAIN)

    assert result.kind is heuristic_only.kind
    assert result.source == "vlm+heuristic"
    assert result.confidence > heuristic_only.confidence
    assert result.confidence <= 1.0


def test_agreement_on_the_first_vote_stops_the_polling() -> None:
    """Эвристика и модель уже сошлись — подтверждать это ещё двумя вызовами незачем."""
    vlm = FakeVlm([verdict("quote")])
    result = LayoutClassifier(vlm=vlm, votes=3).classify(
        UNCERTAIN.placeholders, SLIDE, UNCERTAIN
    )
    assert vlm.calls == 1
    assert result.source == "vlm+heuristic"


def test_escalation_can_be_switched_off() -> None:
    vlm = FakeVlm([verdict("quote")])
    LayoutClassifier(vlm=vlm, votes=3, escalate_on_disagreement=False).classify(
        UNCERTAIN.placeholders, SLIDE, UNCERTAIN
    )
    assert vlm.calls == 3


def test_disagreement_hands_the_verdict_to_the_model() -> None:
    vlm = FakeVlm([verdict("closing")])
    result = LayoutClassifier(vlm=vlm).classify(UNCERTAIN.placeholders, SLIDE, UNCERTAIN)
    assert result.kind is LayoutKind.CLOSING
    assert result.source == "vlm"


def test_majority_wins_over_a_single_dissenter() -> None:
    vlm = FakeVlm([verdict("closing"), verdict("closing"), verdict("quote")])
    result = LayoutClassifier(vlm=vlm, votes=3).classify(
        UNCERTAIN.placeholders, SLIDE, UNCERTAIN
    )
    assert result.kind is LayoutKind.CLOSING
    assert result.confidence == pytest.approx(2 / 3, abs=0.01)


def test_split_vote_is_reflected_in_confidence() -> None:
    """Разнобой между прогонами обязан быть виден в уверенности, а не сглажен."""
    vlm = FakeVlm([verdict("closing"), verdict("quote"), verdict("chart")])
    result = LayoutClassifier(vlm=vlm, votes=3).classify(
        UNCERTAIN.placeholders, SLIDE, UNCERTAIN
    )
    assert result.confidence == pytest.approx(1 / 3, abs=0.01)


# --- устойчивость ------------------------------------------------------------


def test_answer_outside_the_enum_is_not_counted_as_a_vote() -> None:
    """«Вид», которого нет в перечне, — это не `custom`, а несостоявшийся голос."""
    vlm = FakeVlm([{"kind": "красивый", "reason": "…"}, verdict("quote"), verdict("quote")])
    result = LayoutClassifier(vlm=vlm, votes=3).classify(
        UNCERTAIN.placeholders, SLIDE, UNCERTAIN
    )
    assert result.kind is LayoutKind.QUOTE
    assert result.confidence == pytest.approx(1.0)


def test_model_failure_falls_back_to_the_heuristic() -> None:
    """Недоступный инференс не должен оставлять макет без вида."""
    vlm = FakeVlm([RuntimeError("инференс недоступен")])
    result = LayoutClassifier(vlm=vlm, votes=3).classify(
        UNCERTAIN.placeholders, SLIDE, UNCERTAIN
    )
    assert result.source == "heuristic"
    assert result.kind is not None


def test_malformed_answer_falls_back_to_the_heuristic() -> None:
    vlm = FakeVlm([{"нет поля kind": True}])
    result = LayoutClassifier(vlm=vlm, votes=3).classify(
        UNCERTAIN.placeholders, SLIDE, UNCERTAIN
    )
    assert result.source == "heuristic"


def test_preview_failure_does_not_break_classification() -> None:
    class BrokenPreview:
        def render(self, layout: LayoutSpec, slide_cx: int, slide_cy: int) -> bytes:
            raise OSError("нет шрифтов")

    vlm = FakeVlm([verdict("chart")])
    result = LayoutClassifier(vlm=vlm, preview=BrokenPreview()).classify(
        UNCERTAIN.placeholders, SLIDE, UNCERTAIN
    )
    assert vlm.calls == 0
    assert result.source == "heuristic"


# --- экономия вызовов --------------------------------------------------------


def test_identical_geometry_is_asked_only_once() -> None:
    """В шаблоне с двумя мастерами одинаковых макетов много; платить дважды незачем."""
    vlm = FakeVlm([verdict("section")])
    classifier = LayoutClassifier(vlm=vlm, votes=3)
    twin = layout_of(TITLE, NARROW, name="другое имя, та же геометрия")

    first = classifier.classify(UNCERTAIN.placeholders, SLIDE, UNCERTAIN)
    second = classifier.classify(twin.placeholders, SLIDE, twin)

    assert vlm.calls == 3
    assert first == second


def test_narrow_body_really_is_uncertain_for_the_heuristic() -> None:
    """Страховка фикстуры: если эвристика вдруг станет уверенной, тесты выше потеряют смысл."""
    from deckforge.parsing.layout_kind import classify_heuristic, needs_vlm

    _, confidence = classify_heuristic(UNCERTAIN.placeholders, SLIDE)
    assert needs_vlm(confidence)


def test_signature_ignores_names_but_notices_geometry() -> None:
    moved = ph(0, "TITLE", 600_000, 3_000_000, 10_900_000, 1_000_000, TextRole.TITLE)
    assert geometry_signature([TITLE], SLIDE) == geometry_signature([TITLE], SLIDE)
    assert geometry_signature([TITLE], SLIDE) != geometry_signature([moved], SLIDE)


def test_signature_is_resolution_independent() -> None:
    """Один макет в двух шаблонах разного масштаба — это одна и та же структура."""
    small = SlideSize(cx_emu=9_144_000, cy_emu=5_143_500, aspect="16:9")
    scaled = ph(
        0, "TITLE",
        round(TITLE.x * small.cx_emu / SLIDE.cx_emu),
        round(TITLE.y * small.cy_emu / SLIDE.cy_emu),
        round(TITLE.cx * small.cx_emu / SLIDE.cx_emu),
        round(TITLE.cy * small.cy_emu / SLIDE.cy_emu),
        TextRole.TITLE,
    )
    assert geometry_signature([TITLE], SLIDE) == geometry_signature([scaled], small)


# --- превью ------------------------------------------------------------------


def test_schematic_preview_is_a_png_of_the_right_shape() -> None:
    png = SchematicPreview(width_px=400).render(CONFIDENT, SLIDE.cx_emu, SLIDE.cy_emu)
    assert png.startswith(b"\x89PNG")

    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(png))
    assert image.size == (400, round(400 * SLIDE.cy_emu / SLIDE.cx_emu))


def test_schematic_preview_is_deterministic() -> None:
    """Классификация должна быть воспроизводимой, значит и картинка тоже."""
    provider = SchematicPreview()
    first = provider.render(CONFIDENT, SLIDE.cx_emu, SLIDE.cy_emu)
    second = provider.render(CONFIDENT, SLIDE.cx_emu, SLIDE.cy_emu)
    assert first == second


def test_different_layouts_give_different_pictures() -> None:
    provider = SchematicPreview()
    assert provider.render(CONFIDENT, SLIDE.cx_emu, SLIDE.cy_emu) != provider.render(
        UNCERTAIN, SLIDE.cx_emu, SLIDE.cy_emu
    )


def test_description_states_shares_not_raw_emu() -> None:
    text = describe_layout(CONFIDENT, SLIDE.cx_emu, SLIDE.cy_emu)
    assert "title #0" in text and "body #1" in text
    assert "%" in text, "доли площади читаются моделью надёжнее, чем числа в EMU"


def test_classification_is_hashable_and_comparable() -> None:
    a = Classification(LayoutKind.BULLETS, 0.8, "heuristic")
    assert a == Classification(LayoutKind.BULLETS, 0.8, "heuristic")
    assert {a}


def test_uncertainty_threshold_is_shared_with_the_manifest() -> None:
    assert 0.0 < UNCERTAIN_BELOW < 1.0


def test_exhausted_quota_stops_further_calls() -> None:
    """Кончившиеся кредиты не восстановятся к следующему макету — стучаться незачем."""
    from deckforge.inference.client import InferenceQuotaError

    vlm = FakeVlm([InferenceQuotaError("кредиты кончились")])
    classifier = LayoutClassifier(vlm=vlm, votes=3)

    first = classifier.classify(UNCERTAIN.placeholders, SLIDE, UNCERTAIN)
    other = layout_of(TITLE, ph(1, "BODY", 600_000, 5_000_000, 9_000_000, 800_000, TextRole.BODY))
    second = classifier.classify(other.placeholders, SLIDE, other)

    assert vlm.calls == 1, "после исчерпания квоты модель больше не зовут"
    assert classifier.exhausted
    assert classifier.failures["quota"] == 1
    assert first.source == second.source == "heuristic"


def test_ordinary_failure_does_not_stop_the_run() -> None:
    """Разовый сбой — не повод отказаться от модели на всей колоде."""
    vlm = FakeVlm([RuntimeError("разрыв связи")])
    classifier = LayoutClassifier(vlm=vlm, votes=3)
    classifier.classify(UNCERTAIN.placeholders, SLIDE, UNCERTAIN)
    assert not classifier.exhausted
    assert classifier.failures["RuntimeError"] >= 1


def test_schematic_draws_shapes_outside_placeholders() -> None:
    """Картинка без плейсхолдера обязана попасть на схему, иначе модель её не увидит."""
    from deckforge.domain.template import LayoutShape, ShapeKind

    bare = layout_of(TITLE)
    with_photo = bare.model_copy(
        update={
            "shapes": [
                LayoutShape(
                    shape_id="s1", kind=ShapeKind.PICTURE,
                    x=SLIDE.cx_emu // 2, y=0, cx=SLIDE.cx_emu // 2, cy=SLIDE.cy_emu,
                )
            ]
        }
    )
    provider = SchematicPreview()
    assert provider.render(bare, SLIDE.cx_emu, SLIDE.cy_emu) != provider.render(
        with_photo, SLIDE.cx_emu, SLIDE.cy_emu
    )


def test_description_separates_content_slots_from_fixed_decor() -> None:
    """Модель должна понимать: в плейсхолдер класть можно, в оформление макета — нет."""
    from deckforge.domain.template import LayoutShape, ShapeKind

    with_photo = CONFIDENT.model_copy(
        update={
            "shapes": [
                LayoutShape(shape_id="s1", kind=ShapeKind.PICTURE,
                            x=0, y=0, cx=SLIDE.cx_emu // 2, cy=SLIDE.cy_emu)
            ]
        }
    )
    text = describe_layout(with_photo, SLIDE.cx_emu, SLIDE.cy_emu)
    assert "Места под контент" in text
    assert "оформление макета" in text
    assert "picture" in text
