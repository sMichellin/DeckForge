"""Паспорт на холодном шаблоне. Change `the-example-passport` (план Б, 1б; правило 10).

Паспорт меряет места настоящим вписыванием — шрифтами образа, а не подделкой. Холодный
шаблон проверяет, что сборка не падает на незнакомом файле и что каждый рецепт
получает либо паспорт, либо названную причину. Шаблон без слайдов-примеров — тоже
случай: каталога нет, паспортов нет, и это не ошибка (путь `by_design`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deckforge.composition.passport import with_passports
from deckforge.designsystem.derive import derive
from deckforge.designsystem.models import PlaceKind
from deckforge.layout.fonts import FontLibrary
from deckforge.parsing import TemplateParser
from tests.e2e.cold_corpus import cold_templates

COLD_TEMPLATES = cold_templates()

pytestmark = [pytest.mark.cold, pytest.mark.slow]


@pytest.mark.skipif(
    not COLD_TEMPLATES, reason="нет холодных шаблонов: ни в cold/, ни от LibreOffice"
)
@pytest.mark.parametrize("template", COLD_TEMPLATES, ids=lambda p: p.name)
def test_every_recipe_gets_a_passport_or_a_reason(template: Path, tmp_path: Path) -> None:
    manifest = TemplateParser(cache_dir=tmp_path).parse(template)
    ds, report = with_passports(derive(manifest), manifest, FontLibrary.default())

    ids = {recipe.recipe_id for recipe in ds.recipes}
    assert set(report.with_passport) | set(report.rejected) == ids
    assert all(why for why in report.rejected.values())
    for recipe in ds.recipes:
        if recipe.passport is None:
            continue
        for place in recipe.passport.places:
            if place.kind is not PlaceKind.PICTURE:
                assert place.capacity_chars > 0, (recipe.recipe_id, place.place_id)
