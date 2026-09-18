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


# --- настоящий клиент, а не подмена фабрики (замер 18.09) ---------------------


def test_self_hosted_server_gets_the_self_hosted_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка не работала ни в одном окружении: `LanguageToolPublicAPI` сам задаёт
    адрес публичного сервиса и падает с `TypeError` на втором `remote_server`.

    Остальные тесты подменяют `checker_factory` целиком, поэтому этого не видели.
    Здесь подменяется только сетевой класс библиотеки — фабрика настоящая.
    """
    import language_tool_python

    from deckforge.audit.semantic import spelling

    seen: dict[str, object] = {}

    class Recorder:
        def __init__(self, language: str, **kwargs: object) -> None:
            seen["language"] = language
            seen.update(kwargs)

    monkeypatch.setattr(language_tool_python, "LanguageTool", Recorder)
    monkeypatch.setattr(
        language_tool_python,
        "LanguageToolPublicAPI",
        lambda *a, **k: pytest.fail("для своего сервера нужен LanguageTool, а не PublicAPI"),
    )

    assert spelling._language_tool("ru", "http://languagetool:8010") is not None
    assert seen["remote_server"] == "http://languagetool:8010"


def test_dead_server_means_skipped_not_crashed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сервиса нет — клиент падает при создании, проверка уходит в пропущенные.

    На этом держится то, что адрес из настроек можно подавать всегда: иначе
    стенд без LanguageTool ронял бы весь аудит посреди слайдов.
    """
    import language_tool_python

    from deckforge.audit.semantic import spelling

    def refuse(*a: object, **k: object) -> None:
        raise language_tool_python.utils.LanguageToolError("сервер не отвечает")

    monkeypatch.setattr(language_tool_python, "LanguageTool", refuse)
    assert spelling._language_tool("ru", "http://nowhere:8010") is None
