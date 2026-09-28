"""Слово из исходного материала не опечатка. Change `the-source-words-are-not-typos` (RG60).

28.09 на стенде впервые поднят LanguageTool, и `content.no_typos` дал в прогоне `96ef159`
13 предупреждений. Девять из них — «дизайн-систему», «Пайплайн», «промпты»: слова, которые
стоят в задании заказчика. Словарь LanguageTool отраслевых терминов не знает, а мы пишем
словами заказчика.

Пунктуация под исключение не попадает: три её находки из четырёх настоящие, и они нашли
реальный дефект вёрстки — слитые в строку шаги схемы (RG65).

LanguageTool здесь не поднимается: проверка ходит к нему через узкий интерфейс
`SpellChecker`, и подделка отвечает тем же, чем ответил бы сервер.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from deckforge.audit.semantic import spelling
from deckforge.domain.content import Brief, ContentPackage, Fact
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import body, context_for, deck, slide, title

CHECK = "content.no_typos"
#: Термин задания, который словарь LanguageTool считает ошибкой.
TERM = "дизайн-систему"
#: Правило орфографии LanguageTool и правило пунктуации — их судьба разная.
SPELLING_RULE = "MORFOLOGIK_RULE_RU_RU"
PUNCTUATION_RULE = "SENTENCE_WHITESPACE"


class FakeChecker:
    """Отмечает заданное слово заданным правилом, остальное считает верным."""

    def __init__(self, word: str, rule_id: str = SPELLING_RULE) -> None:
        self.word = word
        self.rule_id = rule_id

    def check(self, text: str) -> Sequence[spelling.Typo]:
        offset = text.find(self.word)
        if offset < 0:
            return []
        return [
            spelling.Typo(
                message="Возможно найдена орфографическая ошибка",
                offset=offset,
                length=len(self.word),
                rule_id=self.rule_id,
            )
        ]


def checking(monkeypatch: pytest.MonkeyPatch, word: str, rule_id: str = SPELLING_RULE) -> None:
    monkeypatch.setattr(
        spelling, "checker_factory", lambda language, url: FakeChecker(word, rule_id)
    )


def material(*, markdown: str = "", fact: str = "") -> ContentPackage:
    """Контент-пакет с исходным материалом прогона."""
    return ContentPackage(
        brief=Brief(purpose="report", audience="правление"),
        facts=[Fact(fact_id="f001", text=fact)] if fact else [],
        raw_markdown=markdown or None,
    )


def fragments(manifest: TemplateManifest, text: str, content: ContentPackage | None) -> list[str]:
    colony = deck(slide(title(), body(text)))
    context = context_for(CHECK, colony, manifest, content=content)
    return [f.evidence["fragment"] for f in spelling.no_typos(context)]


def test_a_term_from_the_material_is_not_a_typo(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Норма: слово стоит в задании заказчика дословно."""
    checking(monkeypatch, TERM)

    assert fragments(manifest, f"Сначала извлечь {TERM}", material(markdown=TERM)) == []


def test_another_form_of_the_same_word_is_not_a_typo(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Норма: в колоде «дизайн-систему», в материале «дизайн-система» — одно слово."""
    checking(monkeypatch, TERM)

    source = material(fact="Из шаблона извлекается дизайн-система целиком")
    assert fragments(manifest, f"Сначала извлечь {TERM}", source) == []


def test_a_word_absent_from_the_material_is_still_a_typo(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Нарушитель: настоящая опечатка, которой в материале нет."""
    checking(monkeypatch, "преведствую")

    assert fragments(manifest, "преведствую коллег", material(markdown=TERM)) == ["преведствую"]


def test_punctuation_on_a_word_from_the_material_is_still_a_finding(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Нарушитель: слово из задания, но пропущенная перед ним точка — наша."""
    checking(monkeypatch, "Выделить", rule_id=PUNCTUATION_RULE)

    source = material(markdown="Выделить дизайн-систему шаблона")
    assert fragments(manifest, "Разобрать шаблон Выделить логику", source) == ["Выделить"]


def test_a_short_stem_does_not_excuse_a_typo(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Нарушитель: совпадение только основой короче пяти букв — не оправдание."""
    checking(monkeypatch, "прод")

    assert fragments(manifest, "прод коллег", material(markdown="продукт")) == ["прод"]


def test_without_a_content_package_nothing_is_excused(
    manifest: TemplateManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Норма прежнего поведения: материала нет — сверять не с чем."""
    checking(monkeypatch, TERM)

    assert fragments(manifest, f"Сначала извлечь {TERM}", None) == [TERM]
