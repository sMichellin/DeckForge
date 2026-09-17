"""`content.no_typos`: на нарушителе, на норме и когда сервиса нет. Change (15).

LanguageTool здесь не поднимается: проверка ходит к нему через узкий интерфейс
`SpellChecker`, и подделка отвечает тем же, чем ответил бы сервер. Так тест проверяет
поведение проверки, а не доступность чужого сервиса.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from deckforge.audit.registry import CheckUnavailable
from deckforge.audit.semantic import spelling
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import body, context_for, deck, slide, title


class FakeChecker:
    """Отвечает находкой на заранее известное слово, остальное считает верным."""

    def __init__(self, word: str = "преведствую") -> None:
        self.word = word

    def check(self, text: str) -> Sequence[spelling.Typo]:
        offset = text.find(self.word)
        if offset < 0:
            return []
        return [
            spelling.Typo(
                message="Возможная орфографическая ошибка",
                offset=offset,
                length=len(self.word),
                rule_id="MORFOLOGIK_RULE_RU_RU",
                replacements=("приветствую",),
            )
        ]


@pytest.fixture
def with_checker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spelling, "checker_factory", lambda language, url: FakeChecker())


@pytest.fixture
def without_checker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spelling, "checker_factory", lambda language, url: None)


def test_no_typos_catches_a_misspelling(
    manifest: TemplateManifest, with_checker: None
) -> None:
    colony = deck(slide(title(), body("преведствую коллег")))
    findings = list(spelling.no_typos(context_for("content.no_typos", colony, manifest)))
    assert len(findings) == 1
    assert findings[0].evidence["fragment"] == "преведствую"
    assert "приветствую" in findings[0].message


def test_no_typos_silent_on_clean_text(
    manifest: TemplateManifest, with_checker: None
) -> None:
    colony = deck(slide(title(), body("приветствую коллег")))
    assert list(spelling.no_typos(context_for("content.no_typos", colony, manifest))) == []


def test_no_typos_is_unavailable_without_languagetool(
    manifest: TemplateManifest, without_checker: None
) -> None:
    """Сервиса нет — проверка не запускалась. Молчаливое «опечаток нет» было бы враньём."""
    colony = deck(slide(title(), body("преведствую коллег")))
    with pytest.raises(CheckUnavailable):
        list(spelling.no_typos(context_for("content.no_typos", colony, manifest)))


def test_language_comes_from_the_deck(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Язык берётся из колоды, а не зашит: колода не на русском — правила другие."""
    seen: list[str] = []

    def factory(language: str, url: str | None) -> FakeChecker:
        seen.append(language)
        return FakeChecker()

    monkeypatch.setattr(spelling, "checker_factory", factory)
    colony = deck(slide(title(), body("текст")))
    list(spelling.no_typos(context_for("content.no_typos", colony, manifest)))
    assert seen == [colony.language]
