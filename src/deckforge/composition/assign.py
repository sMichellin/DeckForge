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

from deckforge.composition.passport import COVER_TITLE_LEVELS, TITLE_LEVELS, sample
from deckforge.composition.recipe_picker import (
    INTENT_KINDS,
    RELATED_KINDS,
    on_title_layout,
)
from deckforge.designsystem.models import (
    DesignSystem,
    ExamplePassport,
    Place,
    PlaceKind,
    Recipe,
    RecipeKind,
)
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

#: Сколько слов делает место местом под прозу. Два слова — это подпись («Срок сделки»),
#: три — уже мысль. Планка нужна, чтобы отличить пример, который держит текст, от примера,
#: который держит подписи: у `ex052` VK Tech двенадцать мест — подписи полос и делений
#: шкалы диаграммы Ганта, и проза, разрезанная по ним, читается как обрывки.
PROSE_WORDS = 3

#: Какая доля мест примера должна держать прозу, чтобы в него можно было положить прозу.
#: Ровно половина: у карточек «название + текст» половина мест — короткие названия,
#: и такой пример прозу держит; у шкалы Ганта коротких мест больше половины.
PROSE_SHARE = 0.5


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


def title_place(recipe: Recipe) -> Place | None:
    """Место примера, в которое встанет заголовок слайда: самое просторное своей ступени.

    Ступени — те же, что у паспорта (`passport.TITLE_LEVELS`): на обложке заголовок
    законно набран кеглем `display`, на остальных видах `display` — крупное число.
    """
    if recipe.passport is None:
        return None
    levels = COVER_TITLE_LEVELS if recipe.kind is RecipeKind.COVER else TITLE_LEVELS
    titles = [place for place in recipe.passport.places if place.role in levels]
    return max(titles, key=lambda place: place.capacity_chars, default=None)


def _body_places(recipe: Recipe, heading: Place | None) -> list[Place]:
    """Места примера под текст, кроме заголовка: туда встают факты слайда."""
    if recipe.passport is None:
        return []
    return [
        place
        for place in recipe.passport.places
        if place is not heading
        and place.kind is PlaceKind.TEXT
    ]


def holds_the_slide(recipe: Recipe, slide: SlidePlan) -> bool:
    """Держит ли пример то, что слайду нести: заголовок целиком и факты (К3, круг 2).

    Заголовок утверждён планировщиком, и место, которое держит его наполовину, даёт
    не заголовок, а обрубок: обложка WorkSpace `ex014` — 23 знака при заголовке в 61.
    Факты требуют своего места: у того же `ex014` других текстовых мест нет вовсе,
    и два факта финала просто некуда было положить (`integrity.content_lost`).
    """
    heading = title_place(recipe)
    if heading is None or heading.capacity_chars < len(slide.headline):
        return False
    return not slide.fact_refs or bool(_body_places(recipe, heading))


def _for_prose(recipe: Recipe) -> bool:
    """Держит ли пример прозу или он весь из чисел и подписей (К4, круг 2 плана Б).

    `ex052` VK Tech каталог назвал видом «text», и слайду-прозе он законно достался:
    двенадцать текстовых мест. Но это подписи полос и делений шкалы диаграммы Ганта
    по 3–9 знаков, и абзац, разрезанный по ним, на слайде читается как мусор.

    Считаются места под текст — картинки не в счёт. Место-число и место короче трёх слов
    прозы не держат; больше половины таких — пример не для прозы. Слайду, который сам
    заказал числа (`metrics`), он по-прежнему годится: там места и есть числа.
    """
    if recipe.passport is None:
        return True
    places = [place for place in recipe.passport.places if place.kind is not PlaceKind.PICTURE]
    if not places:
        return True
    prose = sum(
        1
        for place in places
        if place.kind is not PlaceKind.NUMBER
        and len(sample(place.capacity_chars).split()) >= PROSE_WORDS
    )
    return prose >= len(places) * PROSE_SHARE


def _tie(seed: int, slide_id: str, recipe_id: str) -> str:
    """Разрыв ровной ничьей: воспроизводимо и без привязки к порядку каталога."""
    return sha256(f"{seed}:{slide_id}:{recipe_id}".encode()).hexdigest()


def _pick(
    slide: SlidePlan,
    kinds: tuple[RecipeKind, ...],
    catalogue: list[Recipe],
    *,
    used: dict[str, int],
    previous: str | None,
    seed: int,
    structural: bool,
    by_places: bool = True,
) -> Recipe | None:
    points = _points(slide)
    for kind in kinds:
        # Правило про прозу — для содержательного слайда. Структурный (обложка, раздел,
        # финал) несёт заголовок, а не абзац, и короткие места ему нормальны: годится ли
        # ему пример, решает отбор по местам заголовка (К3). Слайд, который сам заказал
        # числа, берёт пример с местами-числами законно — там места и есть числа.
        prose = not structural and kind is not RecipeKind.METRICS
        same = [
            recipe
            for recipe in catalogue
            if recipe.kind is kind
            and recipe.recipe_id != previous
            and used.get(recipe.recipe_id, 0) < MAX_USES
            and (not prose or _for_prose(recipe))
            and (not by_places or holds_the_slide(recipe, slide))
        ]
        if not same:
            continue
        return min(
            same,
            key=lambda recipe: (
                #: Т8: содержательному слайду пример с макета титула, раздела или финала
                #: достаётся последним. Вид макета по имени берётся из словаря
                #: `configs/layout_names.yaml` (`on_title_layout`), а не из слов в коде:
                #: своими словами стандартное «Title and Content» считалось титулом,
                #: а словарь ставит «контент» раньше «титула» и зовёт его содержательным.
                0 if structural else int(on_title_layout(recipe)),
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
            # Отбор по местам — для структурного слайда (К3, круг 2). Содержательному
            # его ставить нельзя: замер по фикстурам показал, что место заголовка
            # содержательных примеров держит заголовок редко, и слайдов с примером
            # осталось бы 2 из 8 вместо 8 — правило остановки круга 2 такое откатывает.
            by_places=structural,
        )
        if chosen is None:
            # Пример был, но не держит заголовок или факты (К3): это другая причина,
            # чем «вида нет вовсе», и в отчёте она обязана читаться по-другому.
            blocked = structural and _pick(
                slide,
                tuple(kind for kind in kinds if kind is not None),
                catalogue,
                used=used,
                previous=previous,
                seed=seed,
                structural=structural,
                by_places=False,
            )
            out.append(
                RecipeAssignment(
                    slide_id=slide.slide_id,
                    reason=_by_places_reason(slide, blocked)
                    if blocked
                    else _no_example_reason(slide, structural, kinds),
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


def _by_places_reason(slide: SlidePlan, blocked: Recipe) -> str:
    """Почему структурному слайду не достался пример, который подходил по виду (К3)."""
    heading = title_place(blocked)
    held = heading.capacity_chars if heading is not None else 0
    if held < len(slide.headline):
        return (
            f"пример {blocked.recipe_id} вида «{blocked.kind.value}» держит в заголовке "
            f"{held} знаков, а заголовок слайда — {len(slide.headline)}: "
            "слайд собирается дизайн-системой"
        )
    return (
        f"у примера {blocked.recipe_id} вида «{blocked.kind.value}» нет места под текст, "
        f"а план дал слайду фактов {len(slide.fact_refs)}: слайд собирается дизайн-системой"
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
