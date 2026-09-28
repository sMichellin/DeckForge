"""Аудит: текст примера ищется с точностью до пробела.
Change `sample-text-is-compared-typographed` (RG54).

Writer пишет не то, что лежит в `SlideIR`: перед записью текст проходит типографику
(`layout.nonbreaking`, правило Т4), и в файле стоит неразрывный пробел после короткого
предлога. 28.09 дословное сравнение объявило текстом автора шаблона весь текст колоды —
51 ложная ошибка на трёх колодах прогона `19e3b7e`. Шов тот же: функция проверки
на готовом `.pptx` и `SlideIR` колоды.
"""

from __future__ import annotations

from pathlib import Path

from deckforge.audit.deterministic.template import sample_text_left
from deckforge.domain.template import TemplateManifest
from deckforge.layout.nonbreaking import bind as nonbreaking
from tests.unit._audit_builders import context_for, deck
from tests.unit.test_sample_text_left_audit import (
    CHECK,
    SAMPLE,
    by_recipe,
    pptx_with,
    with_examples,
)

#: Строка, в которой типографика вёрстки ставит неразрывный пробел — после «по».
OURS = "AI делает слайды по шаблону"


def test_typography_of_the_writer_is_not_sample_text(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    """Норма: в файле наш текст с неразрывным пробелом, в IR — с обычным."""
    written = nonbreaking(OURS)
    assert written != OURS, "проверять нечего: типографика эту строку не меняет"
    path = pptx_with(tmp_path / "deck.pptx", [written])

    context = context_for(CHECK, deck(by_recipe(OURS)), with_examples(manifest), deck_path=path)

    assert list(sample_text_left(context)) == []


def test_sample_text_beside_typographed_ours_is_still_found(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    """Нарушитель: рядом с нашим текстом осталась фраза примера — и цитата как в файле."""
    written = nonbreaking(OURS)
    path = pptx_with(tmp_path / "deck.pptx", [written, SAMPLE])

    findings = list(
        sample_text_left(
            context_for(CHECK, deck(by_recipe(OURS)), with_examples(manifest), deck_path=path)
        )
    )

    assert [f.slide_id for f in findings] == ["s01"]
    assert findings[0].evidence["text"] == SAMPLE


def test_an_extra_space_inside_our_line_is_not_a_finding(
    manifest: TemplateManifest, tmp_path: Path
) -> None:
    """Норма: строка файла отличается от нашей только двойным пробелом."""
    path = pptx_with(tmp_path / "deck.pptx", ["Выручка  выросла на треть"])

    context = context_for(
        CHECK, deck(by_recipe("Выручка выросла на треть")), with_examples(manifest), deck_path=path
    )

    assert list(sample_text_left(context)) == []
