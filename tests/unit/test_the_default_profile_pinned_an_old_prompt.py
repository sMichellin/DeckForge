"""Профиль не закрепляет версию промпта молча. Change `the-default-profile-pinned-an-old-prompt`.

Таск RG25 (`docs/agents/tasks-24-09.md`). `Settings.profile` по умолчанию стоял `"dev"`,
а `prompts/registry.yaml` закрепляет `slide_composer` для профиля `dev` на `1.0.0`.
Значит **каждый прогон через API и CLI шёл на промпте `1.0.0`**, а не на активном.

Нашлось на прогонах RG20 (24.09): в провенансе слайдов стоял `slide_composer@1.0.0`
при активной `1.4.0`. Правка RG4 (схема ответа не просит полей каталога) на стенде
просто не работала, и по отчёту прогона это было не видно.
"""

from __future__ import annotations

from typing import Any

from deckforge.config import Settings
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import DeckIR, Provenance, SlideIR, TextBlock
from deckforge.pipeline.run import _prompt_versions
from deckforge.registry import get_prompt_registry


def test_no_profile_is_pinned_by_default() -> None:
    """Закрепление версии — осознанный выбор, а не умолчание."""
    assert Settings().profile is None


def test_without_a_profile_the_active_version_is_used() -> None:
    registry = get_prompt_registry()
    assert registry.load("slide_composer", profile=Settings().profile).version == (
        registry.resolve_version("slide_composer")
    )


def test_the_dev_pin_still_works_when_asked_for() -> None:
    """Пин не удалён: он полезен, когда его просят явно (`DECKFORGE_PROFILE=dev`)."""
    registry = get_prompt_registry()
    pinned = registry.resolve_version("slide_composer", profile="dev")
    assert pinned != registry.resolve_version("slide_composer")
    assert registry.load("slide_composer", profile="dev").version == pinned


def _slide(version: str | None) -> SlideIR:
    return SlideIR(
        slide_id="s01",
        layout_id="L07",
        variant="A",
        blocks=[TextBlock(block_id="t", placeholder_idx=0, role=TextRole.TITLE, text="Итоги")],
        provenance=Provenance(prompt_version=version) if version else Provenance(),
    )


def _state(*versions: str | None) -> dict[str, Any]:
    deck = DeckIR(
        deck_id="d", variant="A", template_id="t", seed=1,
        slides=[_slide(v) for v in versions],
    )
    return {"deck": deck}


def test_the_report_names_the_versions_that_were_called() -> None:
    """Отчёт называет то, что звали, а не то, что объявлено активным."""
    assert _prompt_versions(_state("slide_composer@1.0.0", "slide_composer@1.0.0")) == [
        "slide_composer@1.0.0"
    ]


def test_two_versions_in_one_deck_are_both_named() -> None:
    """Расхождение внутри колоды не сглаживается: видно обе."""
    assert _prompt_versions(_state("slide_composer@1.0.0", "slide_composer@1.4.0")) == [
        "slide_composer@1.0.0",
        "slide_composer@1.4.0",
    ]


def test_a_deck_without_provenance_gives_an_empty_list() -> None:
    assert _prompt_versions(_state(None)) == []


def test_no_deck_gives_an_empty_list() -> None:
    assert _prompt_versions({}) == []
