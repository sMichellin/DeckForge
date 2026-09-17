"""VLM-судья: голосование, эскалация, порог уверенности. Change (18).

Живой инференс здесь не нужен: судья ходит к модели через узкий протокол `VlmClient`,
и подделка отвечает тем же, чем ответил бы сервер. Так тест проверяет логику вердикта,
а не доступность чужого сервиса.
"""

from __future__ import annotations

from typing import Any

import pytest

from deckforge.audit.registry import REGISTRY, CheckUnavailable
from deckforge.audit.semantic import judge
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import body, context_for, deck, slide, title

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class FakeVlm:
    """Отдаёт заранее заданные ответы по очереди и считает вызовы."""

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.calls = 0
        self.seeds: list[int] = []

    def ask_image(self, *, system: str, user: str, image_png: bytes,
                  schema: dict[str, Any] | None, seed: int) -> dict[str, Any]:
        self.calls += 1
        self.seeds.append(seed)
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


def _yes(reason: str = "всё в порядке") -> dict[str, Any]:
    return {"verdict": "yes", "reason": reason}


def _no(reason: str = "заголовок называет тему") -> dict[str, Any]:
    return {"verdict": "no", "reason": reason}


def test_agreement_costs_one_call(manifest: TemplateManifest) -> None:
    """«Претензий нет» не переспрашиваем: находки всё равно не будет, а три вызова стоят втрое."""
    vlm = FakeVlm(_yes())
    verdict = judge.ask(vlm, check_id="content.has_substance", question="?",
                        image_png=PNG, votes=3)
    assert verdict is not None and verdict.ok
    assert vlm.calls == 1


def test_accusation_is_double_checked(manifest: TemplateManifest) -> None:
    """Обвинение увидит человек, поэтому оно переспрашивается тремя прогонами."""
    vlm = FakeVlm(_no(), _no(), _no())
    verdict = judge.ask(vlm, check_id="content.has_substance", question="?",
                        image_png=PNG, votes=3)
    assert verdict is not None and not verdict.ok
    assert vlm.calls == 3
    assert verdict.confidence == pytest.approx(1.0)
    assert vlm.seeds == [0, 1, 2]


def test_split_vote_lowers_confidence() -> None:
    """Два «нет» против одного «да» — вердикт есть, но уверенность неполная."""
    vlm = FakeVlm(_no(), _yes(), _no())
    verdict = judge.ask(vlm, check_id="content.has_substance", question="?",
                        image_png=PNG, votes=3)
    assert verdict is not None and not verdict.ok
    assert verdict.confidence == pytest.approx(2 / 3)


def test_answer_outside_the_list_is_not_a_vote() -> None:
    """Сбой разбора ответа не должен превращаться в уверенный вердикт (приём из change 5)."""
    vlm = FakeVlm({"verdict": "может быть", "reason": "…"}, _no(), _no())
    verdict = judge.ask(vlm, check_id="content.has_substance", question="?",
                        image_png=PNG, votes=3)
    assert verdict is not None and verdict.votes == 2


def test_no_usable_answers_means_no_verdict() -> None:
    vlm = FakeVlm({"verdict": "", "reason": ""})
    assert judge.ask(vlm, check_id="content.has_substance", question="?",
                     image_png=PNG, votes=1) is None


def _run(check_id: str, colony: object, manifest: TemplateManifest, vlm: FakeVlm,
         **overrides: float | int | str | bool) -> list[Any]:
    registered = REGISTRY.get(check_id)
    assert registered is not None
    context = context_for(check_id, colony, manifest, previews={"s01": PNG}, vlm=vlm,
                          **overrides)
    return list(registered.fn(context))


def test_check_reports_a_finding_on_a_confident_no(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body("Текст"), slide_id="s01"))
    findings = _run("content.headline_is_conclusion", colony, manifest,
                    FakeVlm(_no("заголовок называет тему")))
    assert len(findings) == 1
    assert "заголовок называет тему" in findings[0].message


def test_check_silent_on_yes(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), body("Текст"), slide_id="s01"))
    assert _run("content.headline_is_conclusion", colony, manifest, FakeVlm(_yes())) == []


def test_low_confidence_is_silence_not_approval(manifest: TemplateManifest) -> None:
    """Порог уверенности задран: вердикт есть, но проверка молчит, а не одобряет."""
    colony = deck(slide(title(), body("Текст"), slide_id="s01"))
    findings = _run("content.headline_is_conclusion", colony, manifest,
                    FakeVlm(_no(), _yes(), _no()), vlm_confidence_threshold=0.9)
    assert findings == []


def test_check_is_unavailable_without_previews(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), slide_id="s01"))
    registered = REGISTRY.get("content.has_substance")
    assert registered is not None
    context = context_for("content.has_substance", colony, manifest, vlm=FakeVlm(_yes()))
    with pytest.raises(CheckUnavailable):
        list(registered.fn(context))


def test_check_is_unavailable_without_a_client(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), slide_id="s01"))
    registered = REGISTRY.get("content.has_substance")
    assert registered is not None
    context = context_for("content.has_substance", colony, manifest, previews={"s01": PNG})
    with pytest.raises(CheckUnavailable):
        list(registered.fn(context))


def test_neighbours_check_skips_the_first_slide(manifest: TemplateManifest) -> None:
    """Первому слайду не с чем соседствовать — вопрос про пару задаётся со второго."""
    colony = deck(
        slide(title("Первый"), slide_id="s01"),
        slide(title("Второй"), slide_id="s02"),
    )
    vlm = FakeVlm(_yes())
    context = context_for("content.neighbours_connected", colony, manifest,
                          previews={"s01": PNG, "s02": PNG}, vlm=vlm)
    registered = REGISTRY.get("content.neighbours_connected")
    assert registered is not None
    list(registered.fn(context))
    assert vlm.calls == 1


# --- язык колоды: без модели ------------------------------------------------


def test_single_language_catches_a_foreign_slide(manifest: TemplateManifest) -> None:
    colony = deck(
        slide(title("Выручка выросла"), slide_id="s01"),
        slide(title("Выручка по кварталам"), slide_id="s02"),
        slide(title("Revenue grew by a third this year"), slide_id="s03"),
    )
    findings = list(
        judge.single_language(context_for("content.single_language", colony, manifest))
    )
    assert [f.slide_id for f in findings] == ["s03"]


def test_single_language_allows_latin_terms(manifest: TemplateManifest) -> None:
    """Названия продуктов и термины латиницей — норма для русской колоды, а не смена языка."""
    colony = deck(
        slide(title("Выручка выросла на треть"), slide_id="s01"),
        slide(title("Переходим на Kubernetes и PostgreSQL"), slide_id="s02"),
    )
    context = context_for("content.single_language", colony, manifest)
    assert list(judge.single_language(context)) == []


def test_dominant_script_ignores_digits_and_punctuation() -> None:
    assert judge.dominant_script("37 % — 2026") is None
    assert judge.dominant_script("Выручка") == "cyrillic"
    assert judge.dominant_script("Revenue") == "latin"
