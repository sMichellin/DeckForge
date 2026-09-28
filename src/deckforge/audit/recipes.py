"""Каталог композиций для проверок аудита. Change `recipe-slide-is-audited-by-its-zones` (RG27).

Слайд по рецепту — копия слайда-примера шаблона: лежит он на макете **примера**, а текст
его блоков стоит в зонах рецепта. Проверки, которые меряют такой слайд линейкой макета
из плана, находят дефекты, которых нет: 43 ложные ошибки из 63 на трёх колодах 24.09.
Здесь — одно место, где проверка узнаёт рецепт слайда, его макет и его зоны.

Каталог — из дизайн-системы, которую граф кладёт в контекст аудита. Её нет (вызов вне
графа, старый чекпойнт) — тот же `derive`, которым каталог строит узел `parse`: чистая
функция манифеста без модели и файлов, каталоги совпадают по построению.
"""

from __future__ import annotations

from deckforge.audit.registry import CheckContext
from deckforge.composition.passport import with_passports
from deckforge.designsystem import DesignSystem, derive
from deckforge.designsystem.models import Recipe, Zone
from deckforge.domain.slide import Block, SlideIR
from deckforge.domain.template import TemplateManifest


def catalogue(ctx: CheckContext) -> dict[str, Recipe]:
    """Рецепты шаблона по идентификатору."""
    return {recipe.recipe_id: recipe for recipe in _design_system(ctx).recipes}


def _design_system(ctx: CheckContext) -> DesignSystem:
    design = ctx.design_system
    return design if isinstance(design, DesignSystem) else derive(ctx.manifest)


def catalogue_with_passports(ctx: CheckContext) -> dict[str, Recipe]:
    """Рецепты с паспортом примера (план Б, ADR-009), если пример его получает.

    Дизайн-система графа несёт паспорта только на пути `by_example`; прогоны `legacy`
    и старые снимки их не знают. Тогда паспорт считается здесь тем же `with_passports`,
    что и в композиции: группы мест строятся по геометрии примера, и проверка видит
    карточку, а не ряд, который каталог принял за повтор (VK Tech `ex018`).
    Пример, не прошедший пробную заливку, остаётся без паспорта — как и в каталоге.
    """
    ds = _design_system(ctx)
    # Паспорт хоть у одного — каталог уже прошёл `with_passports`, у остальных его нет
    # по причине (пробная заливка), и пересчёт ничего не изменит.
    if ds.recipes and all(recipe.passport is None for recipe in ds.recipes):
        ds, _ = with_passports(ds, ctx.manifest)
    return {recipe.recipe_id: recipe for recipe in ds.recipes}


def recipe_layout_part(recipe: Recipe, manifest: TemplateManifest) -> str | None:
    """Часть макета, на котором лежит слайд-пример рецепта, — туда его кладёт писатель.

    `Recipe.part_name` — часть самого слайда-примера (`ppt/slides/slideN.xml`), а не его
    макета: писатель копирует пример и берёт **его** макет (`rendering/recipe_slide.py`).
    Не нашли пример или его макет — `None`: сверять не с чем, а гадать хуже, чем промолчать.
    """
    wanted = (recipe.part_name or "").lstrip("/")
    example = next(
        (
            item
            for item in manifest.examples
            if item.slide_index == recipe.example_index
            or (wanted and (item.part_name or "").lstrip("/") == wanted)
        ),
        None,
    )
    if example is None or example.layout_id is None:
        return None
    layout = manifest.layout(example.layout_id)
    return layout.part_name.lstrip("/") if layout is not None else None


def zone_of(slide: SlideIR, block: Block, recipes: dict[str, Recipe]) -> Zone | None:
    """Зона рецепта, в которой стоит блок; `None` — блок не в зоне или зона неизвестна."""
    zone_id = getattr(block, "zone_id", None)
    recipe = recipes.get(slide.recipe_id or "")
    if zone_id is None or recipe is None:
        return None
    return next((zone for zone in recipe.zones if zone.zone_id == zone_id), None)
