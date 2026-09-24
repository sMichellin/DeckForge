"""Схема ответа композитора не спрашивает полей каталога композиций.

Change `composer-response-schema-without-recipe`, таск RG4 зонтичного предложения
`recipe-is-not-the-models-word` (`docs/agents/tasks-24-09.md`).

`slide-recipes` добавил `recipe_id` в `SlideIR` и `zone_id` в блоки, а `SlideIR` — это
ещё и `response_model` промпта `slide_composer`. В `response_omit` их не внесли, схема
ответа их потребовала, и модель их заполняла. Пять прогонов 24.09 упали на записи, а
прогон `3dd589541036` показал, что выдумывались они **на каждом** из десяти слайдов:
на девяти их молча перезаписывал `bind_to_recipe`, и наружу вылезал только закрывающий,
которому рецепта не досталось.

Тот же класс ошибки, что закрыл `code-owned-fields-not-asked`: схема просит то, чего
от модели не ждут.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deckforge.registry import get_prompt_registry

#: Поля, которые заполняет каталог композиций шаблона, а не модель.
CATALOGUE_FIELDS = ("recipe_id", "zone_id", "fit_report")

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _properties(schema: dict[str, object]) -> set[str]:
    """Все имена свойств схемы: и у корня, и у каждого вида блока в `$defs`."""
    names: set[str] = set(schema.get("properties", {}))  # type: ignore[arg-type]
    for definition in schema.get("$defs", {}).values():  # type: ignore[union-attr]
        names |= set(definition.get("properties", {}))
    return names


def test_active_schema_does_not_ask_for_catalogue_fields() -> None:
    bundle = get_prompt_registry().load("slide_composer")
    assert bundle.response_schema is not None, "у активной версии нет схемы ответа"

    asked = _properties(bundle.response_schema) & set(CATALOGUE_FIELDS)
    assert not asked, f"схема ответа всё ещё просит {sorted(asked)}"


def test_the_active_version_is_the_one_without_them() -> None:
    """Версия без полей, лежащая рядом с активированной старой, ничего не меняет."""
    assert get_prompt_registry().load("slide_composer").version == "1.4.0"


def test_the_check_would_have_caught_the_regression() -> None:
    """Страховка проверки: на версии, которая падала, она обязана быть красной."""
    broken = json.loads(
        (PROMPTS_DIR / "slide_composer" / "1.3.1" / "schema.json").read_text(encoding="utf-8")
    )
    assert _properties(broken) & set(CATALOGUE_FIELDS), (
        "1.3.1 больше не просит полей каталога — проверка потеряла смысл"
    )


@pytest.mark.parametrize("field", CATALOGUE_FIELDS)
def test_the_contract_still_carries_them(field: str) -> None:
    """Сужается ответ модели, а не контракт: поля нужны пайплайну и остаются в схеме IR."""
    contract = json.loads(
        (PROMPTS_DIR.parent / "schemas" / "slide_ir.schema.json").read_text(encoding="utf-8")
    )
    carried = set(contract.get("properties", {}))
    for definition in contract.get("$defs", {}).values():
        carried |= set(definition.get("properties", {}))
    assert field in carried, f"{field} исчез из контракта, а должен был только из ответа"


def test_the_prompt_text_says_nothing_about_recipes() -> None:
    """Модель файла не видит (ADR-003): ни рецепта, ни зоны шаблона ей не называют."""
    version = PROMPTS_DIR / "slide_composer" / "1.4.0"
    text = (version / "system.j2").read_text(encoding="utf-8")
    text += (version / "user.j2").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "recipe" not in lowered and "рецепт" not in lowered
    #: «Свободная зона» макета (B10) — другое: это вместимость, а не адрес фигуры.
    assert "zone_id" not in lowered
