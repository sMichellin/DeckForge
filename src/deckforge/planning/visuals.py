"""Словарь визуализаций, которые план может заказать слайду. Change (10) `deck-planning`.

Поле `SlidePlan.suggested_visual` — единственный канал, которым планировщик говорит
композитору «здесь нужны показатели», «здесь схема». До этого change поле ничем
не проверялось, и модель заполняла его видами макетов: прогон `693d464d54fb` —
`visual: section` на восьми слайдах из десяти.

Словарь собирается из доменных перечислений, а не из литералов: новый тип диаграммы
или вид схемы попадает в него сам, без правки этого файла.
"""

from __future__ import annotations

from deckforge.domain.enums import ChartType, SmartArtPattern

#: Заказ без уточнения: вид схемы выберет композитор, тип диаграммы — правило по данным
#: (`visual_selector`), и навязывать их плану незачем.
BARE = ("kpi", "table", "image", "chart", "smartart")


def vocabulary() -> tuple[str, ...]:
    """Всё, что план имеет право заказать слайду."""
    return (
        *BARE,
        *(f"chart:{item.value}" for item in ChartType),
        *(f"smartart:{item.value}" for item in SmartArtPattern),
    )


def normalize(value: str | None) -> str | None:
    """Заказ, приведённый к словарю. `None` — заказа нет или он не из словаря.

    Незнакомое значение именно снимается, а не исправляется на ближайшее: «section» —
    это не испорченный `smartart`, это ответ не на тот вопрос, и угадывать за модель
    значит ставить на слайд схему, которой никто не просил.
    """
    if value is None:
        return None
    text = value.strip().lower().replace(" ", "").replace("::", ":")
    return text if text in vocabulary() else None
