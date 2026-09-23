"""Словарь визуализаций, которые план может заказать слайду. Change (10) `deck-planning`,
change `plan-by-the-design-system`.

Поле `SlidePlan.suggested_visual` — единственный канал, которым планировщик говорит
композитору «здесь нужны показатели», «здесь схема». До этого change поле ничем
не проверялось, и модель заполняла его видами макетов: прогон `693d464d54fb` —
`visual: section` на восьми слайдах из десяти.

Словарь собирается из доменных перечислений, а не из литералов: новый тип диаграммы
или вид схемы попадает в него сам, без правки этого файла.

Элементы дизайн-системы шаблона — цитата, callout, нумерованный и иконочный список —
входят в словарь только вместе с самой дизайн-системой: план заказывает то, что шаблон
умеет нарисовать, и то, о чём ДС сказала, когда это уместно. Без ДС словарь прежний.
"""

from __future__ import annotations

from dataclasses import dataclass

from deckforge.designsystem import DesignSystem
from deckforge.designsystem.models import Recipe, RecipeKind
from deckforge.domain.enums import CalloutTone, ChartType, ListStyle, SmartArtPattern

#: Заказ без уточнения: вид схемы выберет композитор, тип диаграммы — правило по данным
#: (`visual_selector`), и навязывать их плану незачем.
BARE = ("kpi", "table", "image", "chart", "smartart")

#: Заказ плана → вид элемента в `DesignSystem.synthesized`. Заказы названы так, как их
#: понимает композитор: тип блока IR и, через двоеточие, его вид (`tone` у callout,
#: `style` у списка). Маркированного списка здесь нет: это список без заказа.
DESIGN_ORDERS: dict[str, str] = {
    "quote": "quote",
    f"callout:{CalloutTone.INSIGHT.value}": "callout_insight",
    f"callout:{CalloutTone.RISK.value}": "callout_risk",
    f"bullets:{ListStyle.NUMBERED.value}": ListStyle.NUMBERED.value,
    f"bullets:{ListStyle.ICON.value}": ListStyle.ICON.value,
}


#: Вид композиции шаблона → заказ плана. `kpi` и `image` в словаре уже есть — у шаблона
#: с такими рецептами они просто становятся заказом «у шаблона есть готовая композиция»;
#: `cards` и `text` появляются в словаре только вместе с рецептами (change
#: `recipe-kinds-in-the-plan`).
RECIPE_ORDERS: dict[RecipeKind, str] = {
    RecipeKind.METRICS: "kpi",
    RecipeKind.CARDS: "cards",
    RecipeKind.TEXT_WITH_PICTURE: "image",
    RecipeKind.TEXT: "text",
}

#: Как вид композиции называется плану словами. Число повторов подставляется по шаблону:
#: «карточки: 3–5 повторов» — это то, что план должен знать, чтобы не просить пять пунктов
#: там, где у шаблона их три.
RECIPE_PURPOSES: dict[RecipeKind, str] = {
    RecipeKind.METRICS: "Готовая композиция шаблона: ряд показателей с крупными числами",
    RecipeKind.CARDS: "Готовая композиция шаблона: ряд карточек",
    RecipeKind.TEXT_WITH_PICTURE: "Готовая композиция шаблона: текст рядом с картинкой",
    RecipeKind.TEXT: "Готовая композиция шаблона: заголовок и текст",
}


@dataclass(frozen=True)
class DesignOrder:
    """Элемент дизайн-системы, который план может заказать, и когда он уместен.

    `purpose` — тот же текст, что на странице дизайн-системы и в промпте композитора:
    один ответ на вопрос «когда какой», а не три пересказа. Заголовка элемента здесь
    нет: у иконки он взят с образца («иконочный пункт «target»») и плану ничего не говорит.
    """

    order: str
    purpose: str


def design_menu(ds: DesignSystem | None) -> list[DesignOrder]:
    """Что из дизайн-системы шаблона план может заказать слайду.

    Элемент, которого в ДС нет, в меню не попадает: заказ на него композитор выполнить
    не сможет, а вёрстка — нарисовать по шаблону. Порядок — порядок `DESIGN_ORDERS`,
    чтобы промпт не менялся от прогона к прогону.
    """
    if ds is None:
        return []
    purposes: dict[str, str] = {}
    for element in ds.synthesized:
        purposes.setdefault(element.kind, element.purpose)
    elements = [
        DesignOrder(order=order, purpose=purposes[kind])
        for order, kind in DESIGN_ORDERS.items()
        if purposes.get(kind)
    ]
    #: Композиции шаблона идут первыми: слайд целиком по шаблону важнее отдельного
    #: элемента на нём. Заказ, уже названный элементом, не повторяется.
    named = {item.order for item in elements}
    return [item for item in composition_menu(ds) if item.order not in named] + elements


def _plural_repeats(count: int) -> str:
    tail = count % 100
    if 11 <= tail <= 14:
        return "повторов"
    last = count % 10
    if last == 1:
        return "повтор"
    if 2 <= last <= 4:
        return "повтора"
    return "повторов"


def _repeats_words(recipes: list[Recipe]) -> str:
    """Сколько повторов у композиций этого вида — словами, диапазоном.

    Это то, что плану нужно знать, чтобы не просить пять пунктов там, где шаблон
    рисует три.
    """
    counts = sorted({recipe.repeats for recipe in recipes if recipe.repeats})
    if not counts:
        return ""
    if len(counts) == 1:
        return f", {counts[0]} {_plural_repeats(counts[0])}"
    return f", {counts[0]}–{counts[-1]} {_plural_repeats(counts[-1])}"


def composition_menu(ds: DesignSystem | None) -> list[DesignOrder]:
    """Композиции, которые шаблон умеет сам: план называет вид, пример выберет счёт.

    Обложка, перебивка и финал в меню не идут: их слайд получает по своему месту
    в колоде, а не по заказу (решение §4 зонтичного предложения `slide-recipes`).
    """
    if ds is None or not ds.recipes:
        return []
    out: list[DesignOrder] = []
    for kind, order in RECIPE_ORDERS.items():
        same = [recipe for recipe in ds.recipes if recipe.kind is kind]
        if same:
            out.append(
                DesignOrder(order=order, purpose=RECIPE_PURPOSES[kind] + _repeats_words(same))
            )
    return out


def vocabulary(ds: DesignSystem | None = None) -> tuple[str, ...]:
    """Всё, что план имеет право заказать слайду на этом шаблоне."""
    return (
        *BARE,
        *(f"chart:{item.value}" for item in ChartType),
        *(f"smartart:{item.value}" for item in SmartArtPattern),
        *(item.order for item in design_menu(ds)),
    )


def normalize(value: str | None, ds: DesignSystem | None = None) -> str | None:
    """Заказ, приведённый к словарю. `None` — заказа нет или он не из словаря.

    Незнакомое значение именно снимается, а не исправляется на ближайшее: «section» —
    это не испорченный `smartart`, это ответ не на тот вопрос, и угадывать за модель
    значит ставить на слайд схему, которой никто не просил. Так же снимается заказ
    элемента, которого нет в дизайн-системе этого шаблона.
    """
    if value is None:
        return None
    text = value.strip().lower().replace(" ", "").replace("::", ":")
    return text if text in vocabulary(ds) else None
