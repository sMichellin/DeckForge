"""Подбор композиции шаблона под слайд. Change `compose-by-the-recipe`, таск 05b.

Решение §4 зонтичного предложения `slide-recipes`: **вид выбирает план, конкретный
пример — счёт**. Модель выбирает между пятью видами по описанию; выбор между пятьюдесятью
примерами по номерам она делает хуже счёта, а номер примера — это ещё и знание о файле,
которого у генерации по ADR-003 нет.

Здесь только счёт: отбросить не вмещающие, взять ближайший по числу повторов, не ставить
два одинаковых слайда подряд.

Структурный слайд без рецепта своего вида не остаётся на пустом макете (change
`closing-slide-has-a-recipe`, RG8): берёт родственный вид по таблице `RELATED_KINDS`,
а нет и его — вмещающий содержательный. Во всех прогонах 24.09 без рецепта оставался
закрывающий слайд: вида `final` каталог не нашёл ни у одного шаблона кейса.
"""

from __future__ import annotations

from deckforge.designsystem.models import Recipe, RecipeKind
from deckforge.designsystem.recipes import kind_for_visual
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan

#: Место слайда в колоде → вид композиции. Структурный слайд берёт рецепт своего вида
#: и заказом плана не управляется.
INTENT_KINDS: dict[SlideIntent, RecipeKind] = {
    SlideIntent.TITLE: RecipeKind.COVER,
    SlideIntent.SECTION: RecipeKind.SECTION,
    SlideIntent.CLOSING: RecipeKind.FINAL,
}

#: Виды, которые слайд получает по месту в колоде, а не по заказу.
STRUCTURAL = frozenset(INTENT_KINDS.values())

#: Родственные виды структурного слайда — по порядку предпочтения. Таблица, а не
#: эвристика: закрывающий слайд — одна крупная фраза, и по виду он ближе к разделителю,
#: чем к ряду карточек; обложка и разделитель подменяют друг друга.
RELATED_KINDS: dict[SlideIntent, tuple[RecipeKind, ...]] = {
    SlideIntent.TITLE: (RecipeKind.SECTION,),
    SlideIntent.SECTION: (RecipeKind.COVER,),
    SlideIntent.CLOSING: (RecipeKind.SECTION, RecipeKind.COVER),
}


def _needs(slide: SlidePlan) -> int:
    """Сколько повторов нужно слайду: по числу фактов, которые он показывает."""
    return len(slide.fact_refs)


def _fits(recipe: Recipe, slide: SlidePlan, *, has_asset: bool) -> bool:
    """Вмещает ли композиция это содержание.

    Три отказа из спецификации: повторов меньше, чем пунктов; нет зоны под число;
    картинка без ассета.
    """
    if recipe.repeats and recipe.repeats < _needs(slide):
        return False
    if recipe.has_picture and not has_asset:
        return False
    return bool(recipe.zones)


def pick_recipe(
    slide: SlidePlan,
    recipes: list[Recipe],
    previous: str | None = None,
    *,
    has_asset: bool = False,
    notes: list[str] | None = None,
) -> Recipe | None:
    """Композиция под слайд или `None` — тогда слайд собирается прежним путём.

    Структурный слайд берёт рецепт своего вида; нет его — родственного (`RELATED_KINDS`);
    нет и его — вмещающий содержательный. Содержательный — вида, названного планом;
    нет такого вида — любой вмещающий. `None` — каталог пуст или ни один рецепт
    не вмещает содержание слайда.

    `notes` получает откат структурного слайда словами: подмена вида, о которой молчат,
    неотличима от точного совпадения.
    """
    if not recipes:
        return None

    fitting = [
        recipe
        for recipe in recipes
        if recipe.kind not in STRUCTURAL and _fits(recipe, slide, has_asset=has_asset)
    ]
    own = INTENT_KINDS.get(slide.intent)
    if own is not None:
        return _structural(slide, recipes, fitting, own, previous, has_asset, notes)

    wanted = kind_for_visual(slide.suggested_visual)
    named = [recipe for recipe in fitting if recipe.kind is wanted] if wanted else []
    return _nearest(named, slide, previous, has_asset=has_asset) or _nearest(
        fitting, slide, previous, has_asset=has_asset
    )


def _structural(
    slide: SlidePlan,
    recipes: list[Recipe],
    fitting: list[Recipe],
    own: RecipeKind,
    previous: str | None,
    has_asset: bool,
    notes: list[str] | None,
) -> Recipe | None:
    """Рецепт структурного слайда: свой вид → родственный → вмещающий содержательный."""
    for kind in (own, *RELATED_KINDS.get(slide.intent, ())):
        same = [recipe for recipe in recipes if recipe.kind is kind]
        chosen = _nearest(same, slide, previous, has_asset=has_asset)
        if chosen is not None:
            if kind is not own:
                _note_fallback(notes, slide, own, chosen)
            return chosen
    chosen = _nearest(fitting, slide, previous, has_asset=has_asset)
    if chosen is not None:
        _note_fallback(notes, slide, own, chosen)
    elif notes is not None:
        notes.append(
            f"слайд {slide.slide_id}: рецепта вида «{own.value}» в шаблоне нет, "
            "и ни один рецепт каталога не вмещает слайд — собран по макету"
        )
    return chosen


def _note_fallback(
    notes: list[str] | None, slide: SlidePlan, own: RecipeKind, chosen: Recipe
) -> None:
    if notes is not None:
        notes.append(
            f"слайд {slide.slide_id}: рецепта вида «{own.value}» в шаблоне нет, "
            f"взят {chosen.recipe_id} («{chosen.kind.value}»)"
        )


def _nearest(
    recipes: list[Recipe], slide: SlidePlan, previous: str | None, *, has_asset: bool
) -> Recipe | None:
    """Ближайший по числу повторов; при равенстве — не тот, что стоял на прошлом слайде.

    Одинаковые соседние слайды читаются как один: зритель решает, что перелистнули
    назад. Поэтому равенство разрывается не номером примера, а соседством.
    """
    usable = [recipe for recipe in recipes if _fits(recipe, slide, has_asset=has_asset)]
    if not usable:
        return None
    need = _needs(slide)
    usable.sort(key=lambda recipe: (abs(recipe.repeats - need), recipe.recipe_id))
    if previous is not None and len(usable) > 1 and usable[0].recipe_id == previous:
        best = usable[0]
        following = usable[1]
        if abs(following.repeats - need) == abs(best.repeats - need):
            return following
    return usable[0]
