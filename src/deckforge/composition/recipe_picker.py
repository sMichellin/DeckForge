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

from deckforge.composition.recipe_binding import KEEP_SHARE, body_seats
from deckforge.designsystem.models import Recipe, RecipeKind, TypeLevel
from deckforge.designsystem.recipes import kind_for_visual
from deckforge.domain.enums import SlideIntent
from deckforge.domain.plan import SlidePlan
from deckforge.parsing.layout_names import STRUCTURAL_LAYOUTS, load_vocabulary

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


def _title_capacity(recipe: Recipe) -> int:
    """Вместимость зоны заголовка. Нет такой зоны — самой большой: заголовок слайда
    всё равно встанет в неё."""
    titles = [zone for zone in recipe.zones if zone.role is TypeLevel.SLIDE_TITLE]
    zones = titles or recipe.zones
    return max((zone.capacity_chars for zone in zones), default=0)


def _says(slide: SlidePlan, needs_chars: int) -> int:
    """Сколько знаков слайд собирается сказать на самом деле.

    Содержательный — заголовок и факты, как их посчитал композитор. Структурный —
    **только заголовок**: обложка не печатает фактов плана, и мерить ей вместимость
    по ним значит отвергать её за то, чего на ней не будет.

    Прогон RG28 показал, к чему это приводит. У VK WorkSpace одна обложка (`ex014`,
    вместимость 32) и один разделитель (`ex028`, вместимость 0). Обложку отвергала
    эта проверка — 32 знака против половины от всех фактов слайда, — а разделитель
    проходил, потому что вместимость ноль означает «посчитать не удалось» и условие
    молчит. Титульный слайд получал разделитель вместо обложки шаблона.
    """
    return len(slide.headline) if slide.intent in INTENT_KINDS else needs_chars


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
    says = _says(slide, needs_chars)
    return not (holds and says and holds < says * KEEP_SHARE)


def _wanted_seats(slide: SlidePlan) -> int:
    """Сколько мест под тело слайду нужно.

    Содержательному — по числу фактов. Структурному — **одно**: обложка несёт
    подзаголовок, разделитель — пояснение, финал — строку следующего шага, и ни одному
    из них не нужно места по числу фактов плана.

    Ноль здесь был бы неправдой, и прогон это показал: обложке WorkSpace достался
    рецепт `ex028` без единого места, подзаголовок сняли, и слайд уехал в файл
    заголовком на чёрном поле. Одна крупная фраза — законная композиция, поэтому
    отказом это не становится (`_has_room`), но при выборе рецепт с подзаголовком
    обязан быть впереди рецепта без него.
    """
    return 1 if slide.intent in INTENT_KINDS else _needs(slide)


def _short(recipe: Recipe, slide: SlidePlan) -> int:
    """Скольких мест под тело рецепту не хватает. Ноль — хватает всех (RG28).

    Мест — не знаков: `_holds_the_text` считает вместимость, а рецепт с единственной
    заголовочной зоной вмещает сколько угодно знаков в ноль мест.
    """
    return max(0, _wanted_seats(slide) - body_seats(recipe))


def _spare(recipe: Recipe, slide: SlidePlan) -> int:
    """Сколько мест под тело останется лишними. Ноль — рецепт ровно по слайду (RG52).

    Избыток до этого не стоил ничего, и рецепт на девять мест доставался слайду
    с одним фактом наравне с рецептом на одно. Пустые зоны потом снимались (RG40),
    а декор между ними оставался: на превью Education s06 — чертёж из стрелок,
    не ведущих ни к чему, при нулевом аудите. По колоде таких мест было 27 на десяти
    слайдах, и три слайда собраны одним девятиместным `ex013`.

    Весит меньше нехватки: потерять факт хуже, чем оставить пустое место.
    """
    return max(0, body_seats(recipe) - _wanted_seats(slide))


def _has_room(recipe: Recipe, slide: SlidePlan) -> bool:
    """Есть ли в рецепте хоть одно место под тело.

    Отказ — только на нуле мест, и это намеренно. Нехватка мест не равна потере
    содержания: список из трёх пунктов на одном свободном месте встаёт одним абзацем,
    и текст цел. А ноль мест — это ровно `empty_slide`: тело слайда снимается целиком,
    и остаётся заголовок на чёрном поле. Семь слайдов из тридцати в прогоне 25.09 —
    этот случай.

    Нехватка, которая не ноль, решается не отказом, а предпочтением: `_nearest` ставит
    вмещающий рецепт впереди недостаточного, не отвергая второй.

    Структурный слайд не отвергается и на нуле: из 13 рецептов VK Education без единого
    места 8 — обложки, и отказ увёл бы титульный слайд с его вида. Подзаголовок ему
    добывается предпочтением (`_wanted_seats`), а не запретом.
    """
    return slide.intent in INTENT_KINDS or body_seats(recipe) > 0


def _fits(
    recipe: Recipe,
    slide: SlidePlan,
    *,
    has_asset: bool,
    needs_chars: int = 0,
    room: bool = True,
) -> bool:
    """Вмещает ли композиция это содержание.

    Пять отказов: повторов меньше, чем пунктов; картинка без ассета; нет зон;
    текст слайда в зоны не влезает (RG23); под тело нет ни одного места (RG28).

    `room=False` снимает последний отказ — им пользуется `_roomiest`, когда место
    под тело не нашлось ни у одного рецепта каталога.
    """
    if recipe.repeats and recipe.repeats < _needs(slide):
        return False
    if recipe.has_picture and not has_asset:
        return False
    if not recipe.zones:
        return False
    if room and not _has_room(recipe, slide):
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
    explain: dict[str, object] | None = None,
) -> Recipe | None:
    """Композиция под слайд или `None` — тогда слайд собирается прежним путём.

    Структурный слайд берёт рецепт своего вида; нет его — родственного (`RELATED_KINDS`);
    нет и его — вмещающий содержательный. Содержательный — вида, названного планом;
    нет такого вида — любой вмещающий. `None` — каталог пуст или ни один рецепт
    не вмещает содержание слайда.

    `notes` получает откат структурного слайда словами: подмена вида, о которой молчат,
    неотличима от точного совпадения.

    `explain` получает путь выбора — `path`, заказанный вид `wanted`, число вмещающих
    `fitting` (Т7): по нему отчёт прогона отвечает на вопрос «почему этот слайд».
    Словами его собирает `why_recipe`.
    """
    sink: dict[str, object] = explain if explain is not None else {}
    if not recipes:
        sink.update(path="empty", wanted=None, fitting=0)
        return None

    fitting = [
        recipe
        for recipe in recipes
        if recipe.kind not in STRUCTURAL
        and _fits(recipe, slide, has_asset=has_asset, needs_chars=needs_chars)
    ]
    own = INTENT_KINDS.get(slide.intent)
    if own is not None:
        return _structural(
            slide, recipes, fitting, own, previous, has_asset, needs_chars, notes, sink
        )

    wanted = kind_for_visual(slide.suggested_visual)
    named = [recipe for recipe in fitting if recipe.kind is wanted] if wanted else []
    sink.update(wanted=wanted.value if wanted else None, fitting=len(fitting))
    chosen = _nearest(named, slide, previous, has_asset=has_asset, needs_chars=needs_chars)
    sink["path"] = "named"
    if chosen is None:
        chosen = _nearest(fitting, slide, previous, has_asset=has_asset, needs_chars=needs_chars)
        sink["path"] = "fitting"
    if chosen is None:
        chosen = _roomiest(
            slide, recipes, previous, has_asset=has_asset, needs_chars=needs_chars
        )
        sink["path"] = "roomiest" if chosen is not None else "none"
    if chosen is not None:
        _note_short(notes, slide, chosen)
    return chosen


def _note_short(notes: list[str] | None, slide: SlidePlan, chosen: Recipe) -> None:
    """Назвать нехватку мест у выбранного рецепта — каким бы путём он ни выбрался.

    Владельцу видно, что колода собрана с потерей, до того, как он откроет файл.
    Какие именно блоки снялись, называет `bind_to_recipe`: там это уже не оценка
    по плану, а свершившийся факт.
    """
    if notes is None or not (missing := _short(chosen, slide)):
        return
    notes.append(
        f"слайд {slide.slide_id}: в рецепте {chosen.recipe_id} мест под тело "
        f"{body_seats(chosen)} при {_needs(slide)} факт(ах) — часть содержания "
        f"на слайд не встанет (не хватает {missing})"
    )


def _roomiest(
    slide: SlidePlan,
    recipes: list[Recipe],
    previous: str | None,
    *,
    has_asset: bool,
    needs_chars: int,
) -> Recipe | None:
    """Наибольший из безместных — когда места под тело нет ни у одного рецепта (RG28).

    Отката в «нет рецепта» здесь быть не должно: слайд на пустом макете хуже слайда,
    с которого снят один факт. Нехватку называет `_note_short` — одной строкой
    на все пути выбора.

    Выбирает тот же `_nearest`, только без отказа по местам: иначе запасной путь терял
    бы правило соседства, и два слайда подряд вставали бы одной композицией — зритель
    читает такую пару как один слайд, перелистнутый назад.
    """
    return _nearest(
        [recipe for recipe in recipes if recipe.kind not in STRUCTURAL],
        slide,
        previous,
        has_asset=has_asset,
        needs_chars=needs_chars,
        room=False,
    )


def _structural(
    slide: SlidePlan,
    recipes: list[Recipe],
    fitting: list[Recipe],
    own: RecipeKind,
    previous: str | None,
    has_asset: bool,
    needs_chars: int,
    notes: list[str] | None,
    sink: dict[str, object] | None = None,
) -> Recipe | None:
    """Рецепт структурного слайда: свой вид → родственный → вмещающий содержательный.

    Содержательный берётся только **без повторов** (RG24): содержание структурного
    слайда — заголовок, а не список, и набить повторы ему нечем. На VK Tech откат дал
    обложке ряд карточек, карточки остались пустыми и были удалены — на слайде остались
    обрезанный заголовок и логотип. Обложка по макету лучше пустой обложки.
    """
    explain: dict[str, object] = sink if sink is not None else {}
    explain.update(wanted=own.value, fitting=len(fitting))
    for kind in (own, *RELATED_KINDS.get(slide.intent, ())):
        same = [recipe for recipe in recipes if recipe.kind is kind]
        chosen = _nearest(same, slide, previous, has_asset=has_asset, needs_chars=needs_chars)
        if chosen is not None:
            if kind is not own:
                _note_fallback(notes, slide, own, chosen)
            explain["path"] = "own" if kind is own else "related"
            return chosen
    plain = [recipe for recipe in fitting if not recipe.repeats]
    chosen = _nearest(plain, slide, previous, has_asset=has_asset, needs_chars=needs_chars)
    explain["path"] = "plain" if chosen is not None else "none"
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


def on_title_layout(recipe: Recipe) -> bool:
    """Стоит ли пример рецепта на макете, который **по имени** — титул, раздел или финал.

    Заметка владельца 26.09 — про названия («разделение титульник — контент в том числе
    по названию в шаблоне»), поэтому признак — по имени макета через словарь
    `configs/layout_names.yaml`, а не по виду по составу. По виду вышло бы и лишнее,
    и мало: главный содержательный макет VK Education «Заголовок» эвристика уверенно
    зовёт титулом, а три «Титульных» макета VK WorkSpace состав уверенно зовёт иначе.
    """
    return load_vocabulary().kind_of(recipe.layout_name) in STRUCTURAL_LAYOUTS


def _nearest(
    recipes: list[Recipe],
    slide: SlidePlan,
    previous: str | None,
    *,
    has_asset: bool,
    needs_chars: int = 0,
    room: bool = True,
) -> Recipe | None:
    """Ближайший по местам и повторам; при равенстве — не тот, что стоял на прошлом слайде.

    Одинаковые соседние слайды читаются как один: зритель решает, что перелистнули
    назад. Поэтому равенство разрывается не номером примера, а соседством.
    """
    usable = [
        recipe
        for recipe in recipes
        if _fits(recipe, slide, has_asset=has_asset, needs_chars=needs_chars, room=room)
    ]
    if not usable:
        return None
    need = _needs(slide)

    content = slide.intent not in INTENT_KINDS

    def order(recipe: Recipe) -> tuple[int, int, int, int]:
        """Порядок отбора: нехватка мест, макет титула, избыток мест, число повторов.

        Нехватка стоит первой (RG28): рецепт, с которого снимут факт, хуже рецепта,
        отличающегося на один повтор.

        Макет титула — второй (Т8, решение владельца 26.09): содержательный слайд берёт
        пример с макета титула, раздела или финала последним. Такой рецепт остаётся
        в выборе, но только когда вмещающих других нет — слайд в оформлении шаблона
        лучше слайда на пустом макете. Решение владельца весит больше счёта мест.

        Избыток — третий (RG52): среди равных по первым двум ближе тот, у кого мест
        столько, сколько нужно. Лишние зоны снимутся (RG40) и оставят на слайде
        осиротевший декор: на Education рецепт `ex013` дал девять мест на один блок,
        27 пустых мест по колоде и чертёж из стрелок в никуда.
        """
        titled = int(content and on_title_layout(recipe))
        return (
            _short(recipe, slide),
            titled,
            _spare(recipe, slide),
            abs(recipe.repeats - need),
        )

    usable.sort(key=lambda recipe: (*order(recipe), recipe.recipe_id))
    if previous is not None and len(usable) > 1 and usable[0].recipe_id == previous:
        best = usable[0]
        following = usable[1]
        if order(following) == order(best):
            return following
    return usable[0]


#: Путь выбора → как он звучит в отчёте. Одно место, где решение подборщика становится
#: фразой: интерфейс и `run.json` показывают её как есть (Т7).
_WHY: dict[str, str] = {
    "named": "вид «{wanted}» заказан планом — из {fitting} вмещающих взят ближайший по местам",
    "own": "место в колоде задаёт вид «{wanted}» — взят рецепт этого вида",
    "related": "своего вида «{wanted}» в шаблоне нет — взят родственный «{kind}»",
    "plain": (
        "своего вида «{wanted}» и родственных в шаблоне нет — взят вмещающий "
        "содержательный без повторов"
    ),
    "fitting": "заказанного вида нет — из {fitting} вмещающих взят ближайший по местам",
    "roomiest": "ни один рецепт не вмещает содержание — взят самый вместительный",
    "none": "ни один рецепт не подошёл — слайд собран по макету",
    "empty": "у шаблона нет каталога композиций — слайд собран по макету",
}


def why_recipe(explain: dict[str, object], recipe: Recipe | None) -> str:
    """Почему слайд получил этот рецепт — одной фразой для человека (Т7)."""
    path = str(explain.get("path", "none"))
    template = _WHY.get(path, _WHY["none"])
    wanted = explain.get("wanted") or "—"
    return template.format(
        wanted=wanted,
        fitting=explain.get("fitting", 0),
        kind=recipe.kind.value if recipe is not None else "—",
    )
