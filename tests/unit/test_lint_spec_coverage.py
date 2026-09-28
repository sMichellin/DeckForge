"""Гейт «реализация против спецификации». Change `a-block-does-not-go-where-it-does-not-fit`.

В OpenSpec шаг `/opsx:verify` объявлен опциональным, и механики у него нет
(`docs/concepts.md` проекта Fission-AI/OpenSpec). У нас его не было тоже — и 26.09
это стоило красного CI: правка была написана кодом и тестами вперёд предложения.

Гейт проверяет три механические вещи: у предложения есть `proposal.md`, у требования —
сценарий, у change — тест, называющий его по имени. На нарушителе и на норме — как
требует правило 7 AGENTS.md.
"""

from __future__ import annotations

from pathlib import Path

from scripts.lint_spec_coverage import main

DELTA = """# slide-composition

## ADDED Requirements

### Requirement: Блок встаёт туда, где помещается
Раскладка SHALL выбирать зону по вместимости.

#### Scenario: Зона держит текст
- **WHEN** зона держит текст
- **THEN** блок встаёт в неё
"""

NO_SCENARIO = """# slide-composition

## ADDED Requirements

### Requirement: Требование без сценария
Раскладка SHALL что-то делать.
"""


def make_change(root: Path, name: str, *, proposal: bool = True, delta: str | None = None) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    if proposal:
        (folder / "proposal.md").write_text(f"# {name}\n", encoding="utf-8")
    if delta is not None:
        spec = folder / "specs" / "slide-composition"
        spec.mkdir(parents=True)
        (spec / "spec.md").write_text(delta, encoding="utf-8")


def make_test(root: Path, names: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "test_x.py").write_text(f'"""Change `{names}`."""\n', encoding="utf-8")


def run(changes: Path, tests: Path, *, debt: Path | None = None, only: str | None = None) -> int:
    argv = ["--changes", str(changes), "--tests", str(tests), "--debt", str(debt or "/dev/null")]
    if only:
        argv += ["--only", only]
    return main(argv)


def test_a_change_without_a_test_is_red(tmp_path: Path) -> None:
    """Нарушитель: предложение есть, теста нет — доказательства у правки нет."""
    changes, tests = tmp_path / "changes", tmp_path / "tests"
    make_change(changes, "a-zone-holds-the-text", delta=DELTA)
    make_test(tests, "another-change-entirely")

    assert run(changes, tests) == 1


def test_a_test_named_after_the_change_counts(tmp_path: Path) -> None:
    """Норма: имя change стоит в **имени файла** теста, а не в его тексте.

    Так назван тест PR #223 — `test_the_floor_shortens_instead_of_overflowing.py`.
    Гейт его не засчитывал и требовал повторить имя в докстринге: требование пустое,
    доказательство связи и так налицо.
    """
    changes, tests = tmp_path / "changes", tmp_path / "tests"
    make_change(changes, "a-zone-holds-the-text", delta=DELTA)
    tests.mkdir(parents=True)
    (tests / "test_a_zone_holds_the_text.py").write_text('"""Без имени в тексте."""\n')

    assert run(changes, tests) == 0


def test_a_change_with_a_test_is_green(tmp_path: Path) -> None:
    """Норма: тест называет change по имени."""
    changes, tests = tmp_path / "changes", tmp_path / "tests"
    make_change(changes, "a-zone-holds-the-text", delta=DELTA)
    make_test(tests, "a-zone-holds-the-text")

    assert run(changes, tests) == 0


def test_a_requirement_without_a_scenario_is_red(tmp_path: Path) -> None:
    """Нарушитель: требование есть, сценария нет — проверить его нечем.

    «Сценарии обязаны быть тестируемыми» — прямое правило OpenSpec.
    """
    changes, tests = tmp_path / "changes", tmp_path / "tests"
    make_change(changes, "a-zone-holds-the-text", delta=NO_SCENARIO)
    make_test(tests, "a-zone-holds-the-text")

    assert run(changes, tests) == 1


def test_a_change_without_a_proposal_is_red(tmp_path: Path) -> None:
    """Нарушитель: код есть, предложения нет — то, чем и начался этот гейт."""
    changes, tests = tmp_path / "changes", tmp_path / "tests"
    make_change(changes, "a-zone-holds-the-text", proposal=False)
    make_test(tests, "a-zone-holds-the-text")

    assert run(changes, tests) == 1


def test_the_debt_does_not_turn_the_gate_red(tmp_path: Path) -> None:
    """Норма храповика: долг, накопленный до гейта, работу не останавливает."""
    changes, tests = tmp_path / "changes", tmp_path / "tests"
    make_change(changes, "an-old-change", delta=DELTA)
    make_test(tests, "nothing-here")
    debt = tmp_path / "uncovered.txt"
    debt.write_text("# долг\nan-old-change\n", encoding="utf-8")

    assert run(changes, tests, debt=debt) == 0


def test_a_new_change_is_red_even_with_a_debt_list(tmp_path: Path) -> None:
    """Нарушитель храповика: долг есть, но правка новая — поблажки ей нет."""
    changes, tests = tmp_path / "changes", tmp_path / "tests"
    make_change(changes, "an-old-change", delta=DELTA)
    make_change(changes, "a-brand-new-change", delta=DELTA)
    make_test(tests, "nothing-here")
    debt = tmp_path / "uncovered.txt"
    debt.write_text("an-old-change\n", encoding="utf-8")

    assert run(changes, tests, debt=debt) == 1


def test_only_checks_one_change(tmp_path: Path) -> None:
    """`--only` судит одну правку и о чужом долге молчит: так гейт зовут в PR."""
    changes, tests = tmp_path / "changes", tmp_path / "tests"
    make_change(changes, "an-old-change", delta=DELTA)
    make_change(changes, "a-brand-new-change", delta=DELTA)
    make_test(tests, "a-brand-new-change")

    assert run(changes, tests, only="a-brand-new-change") == 0
    assert run(changes, tests, only="an-old-change") == 1
