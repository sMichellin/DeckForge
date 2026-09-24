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

from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel
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

#: Доля текста, ниже которой обрезка перестаёт быть сокращением. От предложения,
#: от которого осталось меньше половины, автора уже не остаётся: на холодном шаблоне
#: зоны вмещали по два знака, и по слайду разъехались одиночные буквы (прогон
#: `cb04bb47fc47`). Одна доля на оба условия отбора — заголовок и содержание целиком.
KEEP_SHARE = 0.5

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


def _title_capacity(recipe: Recipe) -> int:
    """Вместимость зоны заголовка. Нет такой зоны — самой большой: заголовок слайда
    всё равно встанет в неё."""
    titles = [zone for zone in recipe.zones if zone.role is TypeLevel.SLIDE_TITLE]
    zones = titles or recipe.zones
    return max((zone.capacity_chars for zone in zones), default=0)


def _holds_the_text(recipe: Recipe, slide: SlidePlan, needs_chars: int) -> bool:
    """Влезет ли в рецепт то, что слайд собирается сказать.

    Форму композиции (повторы, картинка) `_fits` спрашивал и раньше, а про текст —
    нет, и рецепт с двухзнаковыми зонами считался вмещающим целый слайд. Оба порога
    считаются от содержания самого слайда, а не от чисел шаблона: ни одной константы
    конкретного файла здесь быть не может, на вход подаётся любой.

    Вместимость ноль — её не удалось посчитать (нет кегля у фигуры примера), и тогда
    условие молчит: отсеять рецепт из-за собственного незнания хуже, чем пропустить.
    """
    title = _title_capacity(recipe)
    if title and slide.headline and title < len(slide.headline) * KEEP_SHARE:
        return False
    holds = sum(zone.capacity_chars for zone in recipe.zones)
    return not (holds and needs_chars and holds < needs_chars * KEEP_SHARE)


def _fits(recipe: Recipe, slide: SlidePlan, *, has_asset: bool, needs_chars: int = 0) -> bool:
    """Вмещает ли композиция это содержание.

    Четыре отказа: повторов меньше, чем пунктов; картинка без ассета; нет зон;
    текст слайда в зоны не влезает (RG23).
    """
    if recipe.repeats and recipe.repeats < _needs(slide):
        return False
    if recipe.has_picture and not has_asset:
        return False
    if not recipe.zones:
        return False
    return _holds_the_text(recipe, slide, needs_chars)


def pick_recipe(
    slide: SlidePlan,
    recipes: list[Recipe],
    previous: str | None = None,
    *,
    has_asset: bool = False,
    needs_chars: int = 0,
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
        if recipe.kind not in STRUCTURAL
        and _fits(recipe, slide, has_asset=has_asset, needs_chars=needs_chars)
    ]
    own = INTENT_KINDS.get(slide.intent)
    if own is not None:
        return _structural(slide, recipes, fitting, own, previous, has_asset, needs_chars, notes)

    wanted = kind_for_visual(slide.suggested_visual)
    named = [recipe for recipe in fitting if recipe.kind is wanted] if wanted else []
    return _nearest(
        named, slide, previous, has_asset=has_asset, needs_chars=needs_chars
    ) or _nearest(fitting, slide, previous, has_asset=has_asset, needs_chars=needs_chars)


def _structural(
    slide: SlidePlan,
    recipes: list[Recipe],
    fitting: list[Recipe],
    own: RecipeKind,
    previous: str | None,
    has_asset: bool,
    needs_chars: int,
    notes: list[str] | None,
) -> Recipe | None:
    """Рецепт структурного слайда: свой вид → родственный → вмещающий содержательный.

    Содержательный берётся только **без повторов** (RG24): содержание структурного
    слайда — заголовок, а не список, и набить повторы ему нечем. На VK Tech откат дал
    обложке ряд карточек, карточки остались пустыми и были удалены — на слайде остались
    обрезанный заголовок и логотип. Обложка по макету лучше пустой обложки.
    """
    for kind in (own, *RELATED_KINDS.get(slide.intent, ())):
        same = [recipe for recipe in recipes if recipe.kind is kind]
        chosen = _nearest(same, slide, previous, has_asset=has_asset, needs_chars=needs_chars)
        if chosen is not None:
            if kind is not own:
                _note_fallback(notes, slide, own, chosen)
            return chosen
    plain = [recipe for recipe in fitting if not recipe.repeats]
    chosen = _nearest(plain, slide, previous, has_asset=has_asset, needs_chars=needs_chars)
    if chosen is not None:
        _note_fallback(notes, slide, own, chosen)
    elif notes is not None:
        notes.append(
            f"слайд {slide.slide_id}: рецепта вида «{own.value}» в шаблоне нет, "
            "и ни один рецепт каталога не вмещает слайд без повторов — собран по макету"
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
    recipes: list[Recipe],
    slide: SlidePlan,
    previous: str | None,
    *,
    has_asset: bool,
    needs_chars: int = 0,
) -> Recipe | None:
    """Ближайший по числу повторов; при равенстве — не тот, что стоял на прошлом слайде.

    Одинаковые соседние слайды читаются как один: зритель решает, что перелистнули
    назад. Поэтому равенство разрывается не номером примера, а соседством.
    """
    usable = [
        recipe
        for recipe in recipes
        if _fits(recipe, slide, has_asset=has_asset, needs_chars=needs_chars)
    ]
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
