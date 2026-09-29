"""Примеры на всю колоду до текста. Change `recipes-for-the-whole-deck`, план Б, шаг 2.

Пример выбирался по одному слайду и после ответа модели: `pick_recipe` считал места,
а предыдущий пример узнавался из ответа, который приходит параллельно
(`pipeline/nodes/compose.py`). Отсюда 0 слайдов из 24 с примером по смыслу и один пример
на шести слайдах из десяти (замер 28.09, `scripts/plan_b_metrics.py`).

Здесь примеры выбираются **на всю колоду сразу и до текста** (ADR-009): соседи известны,
повтор виден, а вид примера не подменяется «ближайшим по местам». Модель не участвует —
это счёт (Д5), и одинаковые план, каталог и `seed` дают одинаковый ответ.

Назначения кладутся в состояние графа узлом `assign` (change 2п, тимлид). Прежний путь
(`pick_recipe`, `_roomiest`) не трогается: он живёт до приёмки плана Б.
"""

from __future__ import annotations

from hashlib import sha256

from pydantic import Field

from deckforge.composition.recipe_picker import INTENT_KINDS, RELATED_KINDS
from deckforge.designsystem.models import DesignSystem, ExamplePassport, Recipe, RecipeKind
from deckforge.designsystem.recipes import kind_for_visual
from deckforge.domain.base import DomainModel
from deckforge.domain.plan import DeckPlan, SlidePlan

#: Сколько раз один пример может встретиться в колоде. Третий раз — это уже не шаблон,
#: а один слайд, показанный трижды: на 28.09 один пример занимал 6 слайдов из 10.
MAX_USES = 2

#: Заказы плана, для которых примера не бывает: схему, цитату, callout, график и таблицу
#: колода строит своими данными, а не текстом в чужие места. Такой слайд идёт путём
#: дизайн-системы — это честнее, чем посадить его в пример другого вида.
WITHOUT_EXAMPLE = frozenset({"smartart", "callout", "quote", "chart", "table", "diagram"})

#: Заказы, которые вида примера не называют: список — это список, а каким примером его
#: показать, решает форма слайда. `bullets` сюда же: маркер рисует дизайн-система.
SHAPE_DECIDES = frozenset({"bullets", "list", ""})

#: Сколько пунктов делают слайд рядом карточек, а не абзацем.
CARDS_FROM = 2


class RecipeAssignment(DomainModel):
    """Пример, назначенный слайду до того, как написан текст.

    Живёт в слое композиции, а не в `domain/**`: назначения кладутся в состояние графа
    (решение Р2 плана Б), в `SlidePlan` не попадают и в схему ответа планировщика — тоже.
    """

    slide_id: str = Field(min_length=1)
    recipe_id: str | None = Field(
        default=None, description="None — примера нет, слайд идёт путём by_design"
    )
    reason: str = Field(min_length=1, description="Причина выбора словами, для run.json (Т7)")
    row_fill: dict[str, int] = Field(
        default_factory=dict, description="Ряд паспорта → сколько групп заполнить"
    )


def _points(slide: SlidePlan) -> int:
    """Сколько пунктов слайд собирается показать: столько, сколько фактов ему дал план."""
    return len(slide.fact_refs)


def _row_sizes(passport: ExamplePassport) -> dict[str, int]:
    return {row: len(groups) for row, groups in passport.rows.items()}


def _wanted_kinds(slide: SlidePlan) -> tuple[RecipeKind, ...]:
    """Виды примера, которыми этот слайд можно показать, — по порядку предпочтения.

    Заказ плана назван — берётся он и только он: подмена вида и есть «ближайший
    по местам», который дал 0 из 24. Заказ не назван — вид решает форма слайда:
    два пункта и больше — ряд карточек, один — текст, есть ассет — текст с картинкой.
    """
    order = (slide.suggested_visual or "").split(":", 1)[0]
    if order in WITHOUT_EXAMPLE:
        return ()
    named = kind_for_visual(slide.suggested_visual)
    if named is not None:
        return (named,)
    if order not in SHAPE_DECIDES:
        return ()
    if slide.asset_refs:
        return (RecipeKind.TEXT_WITH_PICTURE, RecipeKind.TEXT)
    if _points(slide) >= CARDS_FROM:
        return (RecipeKind.CARDS, RecipeKind.TEXT)
    return (RecipeKind.TEXT,)


def _row_penalty(recipe: Recipe, points: int) -> int:
    """Насколько ряд примера не подходит слайду.

    Ряд длиннее нужного — лишние группы снимет вёрстка, это дёшево. Ряд короче — пункт
    некуда положить, и такой пример проигрывает: штраф считается по недостающим местам
    и весит больше, чем лишние.
    """
    sizes = [size for size in _row_sizes(recipe.passport).values()] if recipe.passport else []
    if not sizes:
        #: Пример без ряда — одиночные места: годится слайду с одним пунктом.
        return abs(points - 1)
    best = min(sizes, key=lambda size: (size < points, abs(size - points)))
    return (points - best) * 2 if best < points else best - points


def _tie(seed: int, slide_id: str, recipe_id: str) -> str:
    """Разрыв ровной ничьей: воспроизводимо и без привязки к порядку каталога."""
    return sha256(f"{seed}:{slide_id}:{recipe_id}".encode()).hexdigest()


def _structural_last(recipe: Recipe) -> int:
    """Пример со структурного макета достаётся содержательному слайду последним (Т8)."""
    name = (recipe.layout_name or "").casefold()
    return 1 if any(word in name for word in ("титул", "раздел", "финал", "title")) else 0


def _pick(
    slide: SlidePlan,
    kinds: tuple[RecipeKind, ...],
    catalogue: list[Recipe],
    *,
    used: dict[str, int],
    previous: str | None,
    seed: int,
    structural: bool,
) -> Recipe | None:
    points = _points(slide)
    for kind in kinds:
        same = [
            recipe
            for recipe in catalogue
            if recipe.kind is kind
            and recipe.recipe_id != previous
            and used.get(recipe.recipe_id, 0) < MAX_USES
        ]
        if not same:
            continue
        return min(
            same,
            key=lambda recipe: (
                0 if structural else _structural_last(recipe),
                _row_penalty(recipe, points),
                used.get(recipe.recipe_id, 0),
                _tie(seed, slide.slide_id, recipe.recipe_id),
            ),
        )
    return None


def _fill(recipe: Recipe, points: int) -> dict[str, int]:
    if recipe.passport is None:
        return {}
    return {row: min(points, size) for row, size in _row_sizes(recipe.passport).items() if size}


def assign_recipes(plan: DeckPlan, ds: DesignSystem, *, seed: int) -> list[RecipeAssignment]:
    """Примеры на всю колоду: по одному назначению на каждый слайд плана.

    Порядок правил — из issue #243: кандидат только с паспортом; структурный слайд берёт
    свой вид, потом родственный; содержательный — вид, названный планом, и только его;
    форма ряда подбирается по числу пунктов; один пример не больше двух раз и не подряд;
    нет подходящего — `None` и путь `by_design`.
    """
    #: Пример без паспорта не кандидат: писать текст под места, которых не смогли
    #: померить, нечем — пробную заливку он не прошёл (план Б, шаг 1).
    catalogue = [recipe for recipe in ds.recipes if recipe.passport is not None]
    out: list[RecipeAssignment] = []
    used: dict[str, int] = {}
    previous: str | None = None

    for slide in plan.slides:
        own = INTENT_KINDS.get(slide.intent)
        structural = own is not None
        kinds = (own, *RELATED_KINDS.get(slide.intent, ())) if own else _wanted_kinds(slide)
        chosen = _pick(
            slide,
            tuple(kind for kind in kinds if kind is not None),
            catalogue,
            used=used,
            previous=previous,
            seed=seed,
            structural=structural,
        )
        if chosen is None:
            out.append(
                RecipeAssignment(
                    slide_id=slide.slide_id,
                    reason=_no_example_reason(slide, structural, kinds),
                )
            )
            previous = None
            continue
        used[chosen.recipe_id] = used.get(chosen.recipe_id, 0) + 1
        out.append(
            RecipeAssignment(
                slide_id=slide.slide_id,
                recipe_id=chosen.recipe_id,
                reason=_chosen_reason(slide, chosen, structural, own),
                row_fill=_fill(chosen, _points(slide)),
            )
        )
        previous = chosen.recipe_id
    return out


def _chosen_reason(
    slide: SlidePlan, chosen: Recipe, structural: bool, own: RecipeKind | None
) -> str:
    """Причина словами. Она уезжает в `run.json` (Т7) и читается человеком, а не кодом."""
    rows = _row_sizes(chosen.passport) if chosen.passport else {}
    shape = f", ряд на {max(rows.values())}" if rows else ", одиночные места"
    if structural:
        if own is not None and chosen.kind is not own:
            return (
                f"место в колоде — «{slide.intent.value}», вида «{own.value}» у шаблона нет: "
                f"взят родственный «{chosen.kind.value}»{shape}"
            )
        return f"место в колоде — «{slide.intent.value}»: пример вида «{chosen.kind.value}»{shape}"
    order = slide.suggested_visual or "не назван"
    return (
        f"заказ плана «{order}», пунктов {_points(slide)}: "
        f"пример вида «{chosen.kind.value}»{shape}"
    )


def _no_example_reason(
    slide: SlidePlan, structural: bool, kinds: tuple[RecipeKind | None, ...]
) -> str:
    """Почему примера нет. Слово «нет вида» здесь не годится: путь `by_design` — это
    решение, а не неудача подбора, и в отчёте оно обязано читаться именно так."""
    if not kinds:
        return (
            f"заказ плана «{slide.suggested_visual}» примером не показывается: "
            "слайд собирается дизайн-системой"
        )
    names = ", ".join(f"«{kind.value}»" for kind in kinds if kind is not None)
    if structural:
        return f"свободного примера вида {names} в шаблоне не нашлось: слайд по макету"
    return (
        f"свободного примера вида {names} не осталось "
        f"(повтор или соседство): слайд собирается дизайн-системой"
    )
