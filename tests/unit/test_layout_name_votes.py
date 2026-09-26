"""Имя макета — дополнительный голос за его вид. Change `layout-name-votes`, Т8
(`docs/agents/requirements-from-notes-26-09.md`).

Заметка 26.09: «Многие слайды сделаны на титульниках, может давать разделение титульник —
контент в том числе по названию в шаблоне». Решение владельца: имя голосует, состав решает
при расхождении; словарь — в `configs/layout_names.yaml`.

Сценарии — из дельты `openspec/changes/layout-name-votes/specs/layout-classification/`.
"""

from __future__ import annotations

import pytest

from deckforge.designsystem import derive
from deckforge.designsystem.models import RecipeKind
from deckforge.domain.enums import LayoutKind
from deckforge.parsing import TemplateParser
from deckforge.parsing.layout_kind import UNCERTAIN_BELOW, LayoutClassifier
from deckforge.parsing.layout_names import NameVocabulary, load_vocabulary, name_mismatches
from tests.case_templates import case_template
from tests.unit.test_layout_classifier import (
    BODY,
    NARROW,
    SLIDE,
    TITLE,
    FakeVlm,
    layout_of,
    verdict,
)

VOCABULARY = load_vocabulary()
SILENT = NameVocabulary(kinds=(), name_wins_below=0.0)


# --- словарь -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ('1_Слайд "Спасибо!"', LayoutKind.CLOSING),
        ("Финальный с QR + подпись", LayoutKind.CLOSING),
        ("Титульный слайд раздела", LayoutKind.SECTION),
        ("1_Разделитель", LayoutKind.SECTION),
        ("12_Контент", LayoutKind.CUSTOM),
        ("Title and Content", LayoutKind.CUSTOM),
        ("1_Свободный дизайн", LayoutKind.CUSTOM),
        ("2_Титульный слайд", LayoutKind.TITLE),
        ("Title Slide", LayoutKind.TITLE),
        ("Custom Layout 14", None),
        ("Заголовок", None),
    ],
)
def test_the_vocabulary_reads_the_name(name: str, kind: LayoutKind | None) -> None:
    """Порядок видов важен: раздел раньше титула, содержание раньше титула."""
    assert VOCABULARY.kind_of(name) is kind


# --- голос имени -------------------------------------------------------------------------


def test_an_uncertain_heuristic_gives_way_to_the_name() -> None:
    """Нарушитель до правки: макет «Спасибо» уходил в «прочие» или «цитату»."""
    vlm = FakeVlm([verdict("quote")])
    thanks = layout_of(TITLE, NARROW, name='1_Слайд "Спасибо!"')

    result = LayoutClassifier(vlm=vlm, names=VOCABULARY).classify(
        thanks.placeholders, SLIDE, thanks
    )

    assert result.kind is LayoutKind.CLOSING
    assert result.source == "heuristic+name"
    assert result.confidence >= UNCERTAIN_BELOW
    assert vlm.calls == 0, "имя решило — модель звать незачем"


def test_a_confident_heuristic_keeps_its_kind() -> None:
    """Норма решения владельца: при расхождении решает состав."""
    titled = layout_of(TITLE, BODY, name="2_Титульный слайд")

    result = LayoutClassifier(names=VOCABULARY).classify(titled.placeholders, SLIDE, titled)

    assert result.kind is LayoutKind.BULLETS
    assert result.source == "heuristic"


def test_the_mismatch_is_named() -> None:
    layouts = [("2_Титульный слайд", LayoutKind.BULLETS), ("Custom Layout 14", LayoutKind.BULLETS)]
    assert name_mismatches(layouts, VOCABULARY) == [
        ("2_Титульный слайд", LayoutKind.TITLE, LayoutKind.BULLETS)
    ]


def test_a_silent_vocabulary_keeps_the_old_behaviour() -> None:
    """Шаблон без осмысленных имён или пустой словарь — поведение прежнее, модель зовётся."""
    vlm = FakeVlm([verdict("section")])
    thanks = layout_of(TITLE, NARROW, name='1_Слайд "Спасибо!"')

    result = LayoutClassifier(vlm=vlm, votes=1, names=SILENT).classify(
        thanks.placeholders, SLIDE, thanks
    )

    assert result.source == "vlm" and vlm.calls == 1


# --- шаблоны кейса -----------------------------------------------------------------------


def test_vk_tech_gets_a_cover_a_section_and_a_final() -> None:
    """До правки каталог VK Tech не знал ни обложки, ни раздела, ни финала:
    «Спасибо!» и «Титульный слайд» уходили в «прочие», а «Контент» — в титулы."""
    manifest = TemplateParser().parse(case_template("VK Tech шаблон.pptx"), use_cache=False)

    kinds = {recipe.kind for recipe in derive(manifest).recipes}
    assert {RecipeKind.COVER, RecipeKind.SECTION, RecipeKind.FINAL} <= kinds
    content_as_title = [
        layout.name
        for layout in manifest.layouts
        if "Контент" in layout.name and layout.kind is LayoutKind.TITLE
    ]
    assert not content_as_title
