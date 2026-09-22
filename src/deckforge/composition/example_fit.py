"""Выбор макета по слайдам-примерам шаблона. Задача DS5.

Вид макета мы до сих пор **угадывали**: классификатор смотрит на состав и геометрию
плейсхолдеров и называет макет списком, титулом, макетом под диаграмму. Догадка неплохая,
но это догадка, и на VK Tech она ошибается дорого: четыре макета «Содержание» —
заголовок слева сверху, узкие полосы в одну строку справа — классифицированы как `bullets`,
цепочка видов приводит содержательный слайд ровно к ним, и левая половина остаётся пустой
(прогон `bd9846f3aa69`: пустая зона на 9 слайдах из 10). Макеты, где автор шаблона сам
разложил четыре текстовых блока, классифицированы как `custom`, и до них слайд не доходит
никогда: `custom` не входит ни в одну цепочку.

Примеры — это не догадка. Автор шаблона оставил в нём готовые слайды (DS1): у VK Tech их
54, у VK Education 55, у VK WorkSpace 29. Они прямо показывают, что автор кладёт на этот
макет — сколько текстовых блоков, сколько картинок, есть ли диаграмма. PPTAgent
([arXiv:2501.03936](https://arxiv.org/html/2501.03936v1)) описывает элемент макета тройкой
«категория, модальность, содержание» и берёт макет, чья схема совпадает с содержанием
слайда; здесь схема берётся из примеров, а не выводится из плейсхолдеров.

**Примеры главнее классификации** (решение владельца потока A, 22.09): где у макета есть
примеры, слово автора шаблона перевешивает нашу догадку о виде. Где примеров нет, всё
остаётся как было — цепочка видов и вместимость.
"""

from __future__ import annotations

import statistics
from typing import Final

from deckforge.domain.enums import TextRole
from deckforge.domain.plan import SlidePlan
from deckforge.domain.template import (
    LayoutSpec,
    ShapeKind,
    TemplateExample,
    TemplateManifest,
)

#: Из чего складывается схема содержания. Больше категорий не нужно: слайд-план умеет
#: сказать только это, а мерить макет по тому, чего план не знает, — гадание.
TITLE: Final = "title"
TEXT: Final = "text"
PICTURE: Final = "picture"
DATA: Final = "data"
_CATEGORIES: Final = (TITLE, TEXT, PICTURE, DATA)

Schema = dict[str, int]

#: Сколько текстовых блоков подряд ещё считаются «много текста». Пример с пятнадцатью
#: подписями (сетка иконок) не должен выигрывать у слайда с пятью тезисами только потому,
#: что оба «про текст»: расстояние тогда меряет длину списка, а не замысел макета.
_TEXT_CAP: Final = 8


def _example_schema(example: TemplateExample) -> Schema:
    """Схема одного примера: что автор шаблона на него положил.

    Фигуры без текста и без картинки не считаются: это декор шаблона, его рисует макет,
    а не содержание слайда.
    """
    counts = dict.fromkeys(_CATEGORIES, 0)
    for shape in example.shapes:
        if shape.kind is ShapeKind.PICTURE:
            counts[PICTURE] += 1
        elif shape.kind in (ShapeKind.CHART, ShapeKind.TABLE):
            counts[DATA] += 1
        elif shape.role is TextRole.TITLE:
            counts[TITLE] += 1
        elif shape.text_len > 0:
            counts[TEXT] += 1
    counts[TEXT] = min(counts[TEXT], _TEXT_CAP)
    return counts


def layout_schema(layout_id: str, manifest: TemplateManifest) -> Schema | None:
    """Схема примеров макета — медиана по каждой категории. `None`, если примеров нет.

    Медиана, а не среднее: у макета бывает один пример-исключение, и среднее по двум
    примерам «один текст» и «одиннадцать картинок» не описывает ни того, ни другого.
    """
    schemas = [
        _example_schema(example)
        for example in manifest.examples
        if example.layout_id == layout_id
    ]
    if not schemas:
        return None
    return {
        category: int(statistics.median(schema[category] for schema in schemas))
        for category in _CATEGORIES
    }


def slide_schema(slide: SlidePlan) -> Schema:
    """Схема содержания слайда по плану — в тех же категориях, что и у примеров.

    Заголовок есть всегда: план без него не проходит валидацию. Текстовых блоков
    столько, сколько фактов отдал слайду планировщик, — это и есть будущие тезисы.
    """
    return {
        TITLE: 1,
        TEXT: min(len(slide.fact_refs), _TEXT_CAP),
        PICTURE: len(slide.asset_refs),
        DATA: 1 if slide.dataset_ref else 0,
    }


def schema_distance(left: Schema, right: Schema) -> int:
    """Насколько схемы расходятся. Ноль — автор клал на этот макет ровно такое же."""
    return sum(abs(left[category] - right[category]) for category in _CATEGORIES)


def ranked_by_example(
    slide: SlidePlan, manifest: TemplateManifest
) -> list[tuple[int, LayoutSpec]]:
    """Макеты с примерами, от ближайшего к содержанию слайда. Пусто — примеров нет.

    Возвращается расстояние вместе с макетом, а **отбор — не здесь**: кого нельзя отдавать
    содержанию (обложки, макет титула колоды) и сколько макетов пускать в чередование,
    решает `layout_picker`. Здесь только мера близости.

    Порядок при равном расстоянии — по `layout_id`: тот же план обязан давать ту же колоду.
    """
    wanted = slide_schema(slide)
    scored = [
        (schema_distance(schema, wanted), layout)
        for layout in manifest.layouts
        if (schema := layout_schema(layout.layout_id, manifest)) is not None
    ]
    return sorted(scored, key=lambda row: (row[0], row[1].layout_id))
