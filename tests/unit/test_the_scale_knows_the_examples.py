"""Кегль автора своей зоны не считается кеглем не из шкалы.
Change `the-scale-knows-the-examples` (RG59).

В прогоне `96ef159` проверка «кегль не из шкалы» дала 28 предупреждений из 86, и все три
кегля оказались кеглями автора: 18 pt на WorkSpace — кегль тех же фигур в примере
(`slide5.xml`), и он же стоит у 27 зон каталога. На слайде по рецепту писатель берёт кегль
автора зоны и только понижает его (D02).

Пустить кегли всех примеров в общий набор нельзя: замер показал рост с 5 кеглей до 19
на WorkSpace и с 16 до 48 на VK Tech. Поэтому разрешение точечное — у своей зоны, и это
проверяется здесь.
"""

from __future__ import annotations

from dataclasses import replace

from deckforge.audit.deterministic.template import size_not_in_scale, template_sizes
from deckforge.designsystem import derive
from deckforge.designsystem.models import DesignSystem, Recipe, RecipeKind, TypeLevel, Zone
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import body, context_for, deck, slide

CHECK = "template.size_not_in_scale"
#: Кегли, которых нет ни в шкале синтетического шаблона, ни у его плейсхолдеров.
AUTHOR_PT = 17.0
OTHER_ZONE_PT = 21.0
NOWHERE_PT = 13.0


def zone(zone_id: str, xml_id: int, size_pt: float) -> Zone:
    return Zone(
        zone_id=zone_id,
        xml_id=xml_id,
        role=TypeLevel.BODY,
        capacity_chars=120,
        author_size_pt=size_pt,
    )


def catalogue_of(manifest: TemplateManifest, *zones: Zone) -> DesignSystem:
    """Дизайн-система шаблона с одним рецептом на переданных зонах."""
    recipe = Recipe(
        recipe_id="ex001", example_index=1, kind=RecipeKind.TEXT, repeats=0, zones=list(zones)
    )
    return derive(manifest).model_copy(update={"recipes": [recipe]})


def findings(
    manifest: TemplateManifest, size_pt: float, *, zone_id: str | None, design: DesignSystem
) -> list[str]:
    block = body("Тезис", size_pt=size_pt)
    if zone_id is not None:
        block = block.model_copy(update={"zone_id": zone_id, "placeholder_idx": None})
    colony = deck(slide(block).model_copy(update={"recipe_id": "ex001"}))
    context = replace(context_for(CHECK, colony, manifest), design_system=design)
    return [f.evidence["size_pt"] for f in size_not_in_scale(context)]


def test_the_authors_size_of_its_own_zone_is_allowed(manifest: TemplateManifest) -> None:
    """Норма: кегля нет в шкале, но он стоит у автора этой зоны."""
    assert AUTHOR_PT not in set(template_sizes(manifest))
    design = catalogue_of(manifest, zone("z1", 1, AUTHOR_PT), zone("z2", 2, OTHER_ZONE_PT))

    assert findings(manifest, AUTHOR_PT, zone_id="z1", design=design) == []


def test_a_size_nowhere_in_the_template_is_still_a_warning(manifest: TemplateManifest) -> None:
    """Нарушитель: такого кегля нет ни в шкале, ни у плейсхолдеров, ни у своей зоны."""
    design = catalogue_of(manifest, zone("z1", 1, AUTHOR_PT))

    assert findings(manifest, NOWHERE_PT, zone_id="z1", design=design) == ["13"]


def test_the_authors_size_of_another_zone_is_not_allowed(manifest: TemplateManifest) -> None:
    """Нарушитель: кегль автора взят у другой зоны того же рецепта."""
    design = catalogue_of(manifest, zone("z1", 1, AUTHOR_PT), zone("z2", 2, OTHER_ZONE_PT))

    assert findings(manifest, OTHER_ZONE_PT, zone_id="z1", design=design) == ["21"]


def test_a_block_outside_a_zone_is_checked_as_before(manifest: TemplateManifest) -> None:
    """Норма прежнего поведения: у блока нет зоны — сверка только со шкалой."""
    design = catalogue_of(manifest, zone("z1", 1, AUTHOR_PT))

    assert findings(manifest, AUTHOR_PT, zone_id=None, design=design) == ["17"]
    assert findings(manifest, 18.0, zone_id=None, design=design) == []
