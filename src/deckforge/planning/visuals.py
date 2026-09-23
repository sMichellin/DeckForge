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
    return [
        DesignOrder(order=order, purpose=purposes[kind])
        for order, kind in DESIGN_ORDERS.items()
        if purposes.get(kind)
    ]


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
