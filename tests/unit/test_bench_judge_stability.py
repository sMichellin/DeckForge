"""Замер стабильности вердиктов судьи. Критерий выхода change (18).

Проверяется арифметика замера, а не сама модель: ошибка в счётчике даёт красивую цифру
на ровном месте, и именно так замер и врёт. Живой прогон — скриптом, на модели.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import bench_judge_stability as bench  # noqa: E402
from deckforge.domain.enums import TextRole  # noqa: E402
from deckforge.domain.slide import DeckIR, SlideIR, TextBlock  # noqa: E402


def cell(*verdicts: str, check_id: str = "content.has_substance") -> bench.Cell:
    return bench.Cell(slide_id="s01", check_id=check_id, verdicts=list(verdicts))


# --- арифметика ячейки --------------------------------------------------------


def test_cell_agrees_only_when_all_runs_match() -> None:
    assert cell(bench.OK, bench.OK, bench.OK).agrees
    assert not cell(bench.OK, bench.FINDING, bench.OK).agrees


def test_cell_without_an_answer_is_not_answered_everywhere() -> None:
    assert not cell(bench.OK, bench.NO_ANSWER, bench.OK).answered_everywhere
    assert cell(bench.OK, bench.OK, bench.OK).answered_everywhere


def test_accusation_is_counted_from_any_run() -> None:
    assert cell(bench.OK, bench.FINDING, bench.OK).accuses
    assert not cell(bench.OK, bench.OK, bench.OK).accuses


# --- главное свойство отчёта --------------------------------------------------


def test_silence_is_not_agreement(capsys: pytest.CaptureFixture[str]) -> None:
    """Ячейка, где модель молчала во всех прогонах, формально «совпала».

    Наивный счётчик засчитает её и завысит результат. На живом замере такая ячейка
    была, и цифра из-за неё выросла с 100 % на 45 ячейках до 98 % на 47 — в другую
    сторону, но так же неверно.
    """
    cells = [
        cell(bench.NO_ANSWER, bench.NO_ANSWER, bench.NO_ANSWER),
        cell(bench.OK, bench.FINDING, bench.OK),
    ]
    assert bench.report(cells, threshold=0.8) is False
    out = capsys.readouterr().out
    assert "с вердиктом во всех прогонах: 1" in out
    assert "не ответила: 1" in out


def test_threshold_decides_the_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    stable = [cell(bench.OK, bench.OK, bench.OK) for _ in range(9)]
    flaky = [cell(bench.OK, bench.FINDING, bench.OK)]
    assert bench.report([*stable, *flaky], threshold=0.8) is True
    assert bench.report([*stable[:3], *flaky], threshold=0.8) is False
    capsys.readouterr()


def test_report_names_reproducible_accusations(capsys: pytest.CaptureFixture[str]) -> None:
    """Без этой графы цифра пуста: согласие на «претензий нет» даётся даром."""
    bench.report([cell(bench.FINDING, bench.FINDING, bench.FINDING)], threshold=0.8)
    out = capsys.readouterr().out
    assert "с обвинением хотя бы в одном прогоне: 1" in out
    assert "воспроизвелись во всех прогонах: 1" in out


# --- прогон -------------------------------------------------------------------


class FakeJudge:
    """Считает вызовы и отвечает по кругу заданными вердиктами."""

    instances: ClassVar[list[FakeJudge]] = []

    def __init__(self, answers: list[bool]) -> None:
        self.answers = answers
        self.calls: list[dict[str, Any]] = []
        FakeJudge.instances.append(self)


def fake_ask(judge: FakeJudge, **kwargs: Any) -> Any:
    judge.calls.append(kwargs)
    from deckforge.audit.semantic.judge import Verdict

    ok = judge.answers[len(judge.calls) % len(judge.answers)]
    return Verdict(ok=ok, confidence=1.0, reason="", votes=1)


@pytest.fixture
def deck() -> DeckIR:
    slides = [
        SlideIR(
            slide_id=f"s{i:02d}",
            layout_id="L07",
            variant="A",
            blocks=[
                TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text=f"Вывод {i}")
            ],
        )
        for i in (1, 2)
    ]
    return DeckIR(
        deck_id="d1", variant="A", template_id="sha256:" + "0" * 64, seed=1, slides=slides
    )


def test_every_run_gets_a_fresh_judge(
    deck: DeckIR, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Судья пересоздаётся на каждый прогон: общий кэш внутри клиента обнулил бы замер."""
    monkeypatch.setattr(bench, "ask", fake_ask)
    FakeJudge.instances = []
    previews = {slide.slide_id: b"png" for slide in deck.slides}

    bench.measure(deck, previews, lambda: FakeJudge([True]), runs=3)
    assert len(FakeJudge.instances) == 3


def test_single_vote_is_requested(deck: DeckIR, monkeypatch: pytest.MonkeyPatch) -> None:
    """Голосование гасит разброс — замерять стабильность поверх него бессмысленно."""
    monkeypatch.setattr(bench, "ask", fake_ask)
    FakeJudge.instances = []
    previews = {slide.slide_id: b"png" for slide in deck.slides}

    bench.measure(deck, previews, lambda: FakeJudge([True]), runs=1)
    assert all(call["votes"] == 1 for call in FakeJudge.instances[0].calls)


def test_first_slide_has_no_neighbour_to_compare_with(
    deck: DeckIR, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bench, "ask", fake_ask)
    FakeJudge.instances = []
    previews = {slide.slide_id: b"png" for slide in deck.slides}

    cells = bench.measure(deck, previews, lambda: FakeJudge([True]), runs=1)
    pairwise = {c.slide_id for c in cells if c.check_id == bench.PAIRWISE}
    assert pairwise == {"s02"}


def test_each_cell_collects_one_verdict_per_run(
    deck: DeckIR, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bench, "ask", fake_ask)
    FakeJudge.instances = []
    previews = {slide.slide_id: b"png" for slide in deck.slides}

    cells = bench.measure(deck, previews, lambda: FakeJudge([True]), runs=3)
    assert cells and all(len(c.verdicts) == 3 for c in cells)


def test_slide_without_a_preview_is_not_asked_about(
    deck: DeckIR, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Судье нечего показать — вопрос не задаётся, а не считается пройденным."""
    monkeypatch.setattr(bench, "ask", fake_ask)
    FakeJudge.instances = []

    cells = bench.measure(deck, {"s01": b"png"}, lambda: FakeJudge([True]), runs=1)
    assert {c.slide_id for c in cells} == {"s01"}
