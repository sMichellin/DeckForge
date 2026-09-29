"""Текст пишется под места примера. Change `the-text-is-written-for-the-places`, шаг 3.

Модель писала текст под макет, а о примере знала одно число — ёмкость самой тесной
зоны (`composer._target_chars`). Раскладка потом снимала лишнее, сплющивала схемы
в строку и склеивала пункты: на трёх колодах 28.09 — 11 снятых блоков и 5 сокращений
кодом. Это не сбой раскладки, а её устройство: она получает готовый текст и чужие места.

Здесь порядок обратный (ADR-009). Схема ответа собирается из паспорта назначенного
примера: место — поле с пределом знаков, ряд — массив ровно на столько групп, сколько
назначил шаг 2. Лимит держит грамматика, а не текст промпта (Д4). Ответ ложится
в места один к одному — копирование, а не подбор.

Знаки — не ширина: «ЩЖЮ» шире «ilt» при равной длине, и место с пределом в сорок знаков
сорок широких знаков не держит. Поэтому за схемой остаётся замер тем же вписыванием,
которым мерился паспорт (`passport.fit_measure`), один повторный запрос с настоящим
пределом этого текста и обрезка по словам последним шагом.

`bind_to_recipe` не трогается: раскладка силой остаётся прежнему пути до приёмки.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from deckforge.composition.passport import Fits, capacity
from deckforge.designsystem.models import (
    ExamplePassport,
    Place,
    PlaceGroup,
    PlaceKind,
    Recipe,
    TypeLevel,
)
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import TextBlock

#: Во сколько раз предел поля схемы шире ёмкости места (К1, круг 2 плана Б). Грамматика
#: llama.cpp держит `maxLength` знаками и обрывает генерацию ровно на нём: предел, равный
#: ёмкости, режет слово посреди («AI не копирует фирменны»). Полтора — воздух закончить
#: мысль; настоящий предел модель узнаёт из текста промпта, а не из схемы.
SLACK = 1.5

#: Сколько знаков держит место под номер карточки. Три — это «01»–«999»: показатель
#: «37,5 %» в такое место не встанет, а номер встанет. Граница отличает нумерацию ряда,
#: которую ставит код, от показателя, который пишет модель.
ORDINAL_CHARS = 3

#: Чем считается цифра в материале слайда: ей и только ей место-число имеет право
#: заполниться. Одна цифра где угодно в заголовке или фактах — грубо и намеренно:
#: «37,5 %», «10x», «2024» одинаково годятся, а слайд без единой цифры число взять
#: неоткуда, и просить его у модели — значит просить выдумать.
DIGIT = re.compile(r"\d")

#: Имя места внутри группы ряда: группы одного ряда одной формы, а `place_id` у них
#: разные, и знать оба модели незачем. `t1`, `t2` — позиции мест в группе по порядку
#: паспорта, то есть по порядку чтения.
ROW_ITEM_PREFIX = "t"


def _text_places(group: PlaceGroup) -> list[Place]:
    """Места группы, которые заполняет текст. Картинку подменяет ассет, а не модель."""
    return [place for place in group.places if place.kind is not PlaceKind.PICTURE]


def ceiling(hard: int, longest_word: int = 0) -> int:
    """Предел поля схемы над настоящим пределом места (К1).

    Полторы ёмкости — воздух закончить мысль. Но у тесного места полтора не дают и слова:
    у места на 3 знака («10x») потолок вышел бы 5, и «презентаций» оборвалось бы снова.
    Поэтому не меньше, чем ёмкость плюс самое длинное слово материала слайда: запас
    меряется тем же, чем пишут, — словами, а не долями.
    """
    hard = max(1, hard)
    return max(round(hard * SLACK), hard + longest_word)


def longest_word(texts: Iterable[str]) -> int:
    """Самое длинное слово материала слайда — мерило запаса для тесных мест."""
    return max((len(word) for text in texts for word in text.split()), default=0)


def _limits(place: Place, chars: int | None = None, longest: int = 0) -> dict[str, Any]:
    """Поле схемы под одно место: строка не пустая и не длиннее потолка с запасом.

    Предел не бывает нулевым: `minLength: 1` с `maxLength: 0` — неисполнимая схема,
    и грамматика отдала бы пустую строку, то есть потеряла бы место. Место, которое
    не держит и одного слова, повторным запросом не сокращают вовсе (`shorten_request`
    его не называет), а текст в нём оставляют вёрстке.
    """
    hard = chars if chars is not None else place.capacity_chars
    return {"type": "string", "maxLength": ceiling(hard, longest), "minLength": 1}


def has_numbers(texts: Iterable[str]) -> bool:
    """Есть ли слайду откуда взять число: цифра в заголовке или в фактах плана."""
    return any(DIGIT.search(text) for text in texts)


def ordinals(passport: ExamplePassport, row_fill: dict[str, int]) -> dict[str, str]:
    """Номера карточек, которые ставит код: `place_id` → «01», «02», … (К2, круг 2).

    Место-число внутри ряда, держащее не больше трёх знаков, — это нумерация карточек,
    а не показатель: «37,5 %» туда не встанет. Модель такое место не получает вовсе —
    иначе она пишет в него «1» на каждой карточке (VK Tech s08, четыре единицы подряд).
    Ведущий ноль — когда место держит два знака и больше: так набирает автор.
    """
    out: dict[str, str] = {}
    for row, groups in passport.rows.items():
        for index, group in enumerate(groups[: row_fill.get(row, 0)], start=1):
            for place in group.places:
                if place.kind is PlaceKind.NUMBER and place.capacity_chars <= ORDINAL_CHARS:
                    out[place.place_id] = (
                        f"{index:02d}" if place.capacity_chars >= 2 else str(index)
                    )
    return out


def asked_places(
    passport: ExamplePassport, row_fill: dict[str, int], *, numbers: bool
) -> set[str]:
    """Какие места спрашиваются у модели (К2, круг 2).

    Текстовое место — всегда. Место-число — только если слайду есть откуда взять число:
    на прогоне 29.09 все 24 заполнения мест-чисел пришлись на слайды, где в фактах
    не было ни одной цифры, и 19 из них аудит назвал выдуманными. Номер карточки ряда
    не спрашивается никогда — его ставит код.
    """
    written_by_code = set(ordinals(passport, row_fill))
    out: set[str] = set()
    for group in passport.groups:
        for place in _text_places(group):
            if place.place_id in written_by_code:
                continue
            if place.kind is PlaceKind.NUMBER and not numbers:
                continue
            out.add(place.place_id)
    return out


def _singles(passport: ExamplePassport) -> list[Place]:
    """Места вне ряда: заголовок слайда, подпись, одиночный абзац."""
    return [
        place
        for group in passport.groups
        if group.row is None
        for place in _text_places(group)
    ]


def response_schema(
    passport: ExamplePassport,
    row_fill: dict[str, int],
    tighter: dict[str, int] | None = None,
    longest: int = 0,
    asked: set[str] | None = None,
) -> dict[str, Any]:
    """Схема ответа композитора для этого примера.

    Одиночное место — поле с пределом знаков. Ряд — массив ровно на `row_fill[ряд]`
    объектов: столько групп заполняется, ни больше ни меньше. Ряд, которому заполнение
    не назначено, в схему не идёт — просить текст в места, которых слайду не дали, незачем.

    `tighter` — пределы повторного запроса по `place_id`: место, чей текст не встал
    по ширине глифов, просится короче замеренного, а не тем же числом, которое уже
    подвело. У ряда предел ставится месту той же позиции во всех его группах: схема
    ряда одна на все повторы, и разные пределы в ней не выразить.
    """
    tighter = tighter or {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for place in _singles(passport):
        if asked is not None and place.place_id not in asked:
            continue
        properties[place.place_id] = _limits(place, tighter.get(place.place_id), longest)
        required.append(place.place_id)
    for row, groups in passport.rows.items():
        count = row_fill.get(row, 0)
        if count <= 0:
            continue
        places = _text_places(groups[0])
        if not places:
            continue
        item_props: dict[str, Any] = {}
        for index, place in enumerate(places, start=1):
            # Место, которого слайду не заказывали (место-число без чисел в фактах)
            # или которое пишет код (номер карточки), у модели не спрашивается.
            if asked is not None and place.place_id not in asked:
                continue
            tight = [
                chars
                for group in groups[:count]
                if (peer := _text_places(group)[index - 1 : index])
                and (chars := tighter.get(peer[0].place_id)) is not None
            ]
            item_props[f"{ROW_ITEM_PREFIX}{index}"] = _limits(
                place, min(tight) if tight else None, longest
            )
        if not item_props:
            continue
        properties[row] = {
            "type": "array",
            "minItems": count,
            "maxItems": count,
            "items": {
                "type": "object",
                "properties": item_props,
                "required": list(item_props),
                "additionalProperties": False,
            },
        }
        required.append(row)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def places_brief(
    passport: ExamplePassport, row_fill: dict[str, int], asked: set[str] | None = None
) -> dict[str, Any]:
    """Места примера словами для промпта: что это за место и сколько в него знаков.

    Координат в брифе нет (ADR-003, PPTBench): модель файла не видит, ей уходят
    ступень лестницы и предел знаков — теми же словами, какими промпт называл
    вместимость плейсхолдеров.
    """
    singles = [
        {
            "place_id": place.place_id,
            "role": place.role.value if place.role else "",
            "chars": place.capacity_chars,
            "number": place.kind is PlaceKind.NUMBER,
        }
        for place in _singles(passport)
        if asked is None or place.place_id in asked
    ]
    rows = []
    for row, groups in passport.rows.items():
        count = row_fill.get(row, 0)
        if count <= 0 or not _text_places(groups[0]):
            continue
        if asked is not None and not any(
            place.place_id in asked for place in _text_places(groups[0])
        ):
            continue
        rows.append(
            {
                "row": row,
                "count": count,
                # Ключ не `items`: у словаря Jinja возьмёт метод `.items`, а не значение.
                "cells": [
                    {
                        "key": f"{ROW_ITEM_PREFIX}{index}",
                        "role": place.role.value if place.role else "",
                        "chars": min(
                            _text_places(group)[index - 1].capacity_chars
                            for group in groups[:count]
                            if len(_text_places(group)) >= index
                        ),
                        "number": place.kind is PlaceKind.NUMBER,
                    }
                    for index, place in enumerate(_text_places(groups[0]), start=1)
                    if asked is None or place.place_id in asked
                ],
            }
        )
    return {"single_places": singles, "place_rows": rows}


def _role_of(place: Place) -> TextRole:
    """Роль блока — как у раскладки по зонам: заголовок слайда отличается от тела."""
    return TextRole.TITLE if place.role is TypeLevel.SLIDE_TITLE else TextRole.BODY


def _block(place: Place, text: str, index: int) -> TextBlock:
    return TextBlock(
        block_id=f"b{index:02d}",
        role=_role_of(place),
        text=text,
        zone_id=place.zone_id,
    )


def _written(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def blocks_for_places(
    passport: ExamplePassport,
    row_fill: dict[str, int],
    answer: dict[str, Any],
    written: dict[str, str] | None = None,
) -> list[TextBlock]:
    """Ответ модели, разложенный по местам один к одному.

    Ни снятия, ни склейки: мест ровно столько, сколько заказала схема. Место, которого
    в ответе нет, блоком не становится — его не написали, и выдумывать за модель нечем.
    Порядок блоков — порядок мест паспорта, то есть порядок чтения примера.
    """
    written = written or {}
    out: list[TextBlock] = []
    for place in _singles(passport):
        text = written.get(place.place_id) or _written(answer.get(place.place_id))
        if text is not None:
            out.append(_block(place, text, len(out) + 1))
    for row, groups in passport.rows.items():
        answered = answer.get(row)
        items = answered if isinstance(answered, list) else []
        # Группы ряда перебираются всегда, а не только когда ряд есть в ответе: место,
        # которое пишет код (номер карточки), модель не заказывала и в ответ не клала.
        for index, group in enumerate(groups[: row_fill.get(row, 0)]):
            item = items[index] if index < len(items) else None
            cell = item if isinstance(item, dict) else {}
            for position, place in enumerate(_text_places(group), start=1):
                text = written.get(place.place_id) or _written(
                    cell.get(f"{ROW_ITEM_PREFIX}{position}")
                )
                if text is not None:
                    out.append(_block(place, text, len(out) + 1))
    return out


def merged(first: dict[str, Any], retried: dict[str, Any]) -> dict[str, Any]:
    """Ответ повтора, положенный поверх первого: пустое место не отнимает написанное.

    Повторный запрос называет одно-два места, а схема требует все, и модель переписывает
    заодно и то, о чём не просили. Пустая строка в ответе повтора — не решение «здесь
    ничего не надо», а осечка: на WorkSpace `ex024` место заголовка в девять знаков
    вернулось пустым, и слайд остался без заголовка при непустом первом ответе.
    """
    out = dict(first)
    for key, value in retried.items():
        if isinstance(value, str):
            if value.strip():
                out[key] = value
            continue
        if not isinstance(value, list):
            continue
        was = first.get(key)
        if not isinstance(was, list):
            out[key] = value
            continue
        rows: list[Any] = []
        for index, item in enumerate(value):
            before = was[index] if index < len(was) else None
            if isinstance(item, dict) and isinstance(before, dict):
                rows.append({**before, **{k: v for k, v in item.items() if str(v).strip()}})
            else:
                rows.append(item if str(item).strip() or before is None else before)
        rows.extend(was[len(value):])
        out[key] = rows
    return out


def _by_words(text: str) -> Callable[[int], str]:
    """Обрезка текста по словам: `make(n)` — самое длинное начало не длиннее n знаков.

    По словам, а не по знакам: обрубок посреди слова — это не сокращение, а брак,
    и на холодном шаблоне так уехали в колоду одиночные буквы (прогон `cb04bb47fc47`).
    """

    words = text.split()

    def make(chars: int) -> str:
        taken: list[str] = []
        for word in words:
            candidate = " ".join([*taken, word])
            if len(candidate) > chars:
                break
            taken.append(word)
        return " ".join(taken)

    return make


def overflowing_places(
    recipe: Recipe, fits: Fits, blocks: list[TextBlock]
) -> dict[str, int]:
    """Места, чей текст не встал, и сколько знаков в них **действительно** держится.

    Мерило — то же вписывание, которым мерился паспорт (`passport.fit_measure`): иначе
    схема обещала бы одно, а вёрстка показывала другое. Замеряется весь слайд разом,
    как его и будут верстать, а предел каждого не вставшего места ищется двоичным
    поиском по его же тексту — не по пробным «ы», а по тем словам, которые написала
    модель. Поэтому предел повторного запроса — факт, а не догадка со скидкой.

    Пусто — всё встало, и повторный запрос не нужен.
    """
    zones = {zone.zone_id: zone for zone in recipe.zones}
    texts = {
        block.zone_id: block.text
        for block in blocks
        if block.zone_id is not None and block.zone_id in zones
    }
    if not texts:
        return {}
    landed = fits(recipe, texts)
    limits: dict[str, int] = {}
    for zone_id, text in texts.items():
        if landed.get(zone_id, True):
            continue
        limits[zone_id] = capacity(
            recipe, zones[zone_id], fits, ceiling=len(text), make=_by_words(text)
        )
    return limits


def _ceilings(
    passport: ExamplePassport, row_fill: dict[str, int], schema: dict[str, Any]
) -> dict[str, int]:
    """Потолок поля схемы по зоне каждого места — тем же обходом, каким схема собрана."""
    props = schema.get("properties") or {}
    out: dict[str, int] = {}
    for place in _singles(passport):
        spec = props.get(place.place_id)
        if isinstance(spec, dict) and place.zone_id:
            out[place.zone_id] = int(spec.get("maxLength") or 0)
    for row, groups in passport.rows.items():
        spec = props.get(row)
        if not isinstance(spec, dict):
            continue
        fields = (spec.get("items") or {}).get("properties") or {}
        for group in groups[: row_fill.get(row, 0)]:
            for index, place in enumerate(_text_places(group), start=1):
                field = fields.get(f"{ROW_ITEM_PREFIX}{index}")
                if isinstance(field, dict) and place.zone_id:
                    out[place.zone_id] = int(field.get("maxLength") or 0)
    return out


def at_the_ceiling(
    passport: ExamplePassport,
    row_fill: dict[str, int],
    blocks: list[TextBlock],
    schema: dict[str, Any],
) -> dict[str, int]:
    """Места, чей текст упёрся в потолок схемы: зона → настоящая ёмкость места (К1).

    Грамматика обрывает генерацию ровно на `maxLength`, поэтому текст такой длины —
    не выбор модели, а обрыв: «AI не копирует фирменны». Замер вписывания его не ловит,
    потому что обрубок короче места и «встаёт». Ловится он только так — по длине,
    и только потому, что потолок стоит выше настоящего предела: у текста, который писали
    свободно, ровно потолок — совпадение на один знак из полутора ёмкостей.
    """
    ceilings = _ceilings(passport, row_fill, schema)
    caps = {
        place.zone_id: place.capacity_chars
        for place in passport.places
        if place.zone_id is not None
    }
    out: dict[str, int] = {}
    for block in blocks:
        zone_id = block.zone_id
        if zone_id is None:
            continue
        top = ceilings.get(zone_id)
        if top and len(block.text) >= top:
            out[zone_id] = caps.get(zone_id) or len(block.text)
    return out


def by_place(passport: ExamplePassport, by_zone: dict[str, int]) -> dict[str, int]:
    """Пределы, названные местами паспорта, а не зонами рецепта.

    Модель знает места (`place_id`) — зоны рецепта ей не показывают вовсе: зона живёт
    в каталоге композиций, а паспорт — это контракт потоков A и B.
    """
    return {
        place.place_id: by_zone[place.zone_id]
        for place in passport.places
        if place.zone_id is not None and place.zone_id in by_zone
    }


def shorten_request(places: dict[str, int]) -> str:
    """Один повторный запрос: какие места сократить и до скольких знаков.

    Один, а не цикл: больше двух самоисправлений на слайд не окупаются (PPTAgent,
    [arXiv:2501.03936](https://arxiv.org/html/2501.03936v1)).
    """
    parts = ", ".join(
        f"{place_id} — до {chars} знаков" for place_id, chars in sorted(places.items())
    )
    return (
        "Текст этих мест не встал: знаков в пределе, а ширины букв нет. "
        f"Напиши их короче, не теряя мысли: {parts}. Остальные места оставь как были."
    )


def trimmed_to_fit(
    blocks: list[TextBlock], by_zone: dict[str, int]
) -> tuple[list[TextBlock], dict[str, tuple[int, int]]]:
    """Обрезка по словам последним шагом: что не встало и после повтора.

    Возвращает блоки и обрезанные места — было и осталось знаков, чтобы вызывающий
    назвал потерю в отчёте. Молчаливая обрезка — подмена содержания, о которой никто
    не узнает (RG23).
    """
    out: list[TextBlock] = []
    cut: dict[str, tuple[int, int]] = {}
    for block in blocks:
        limit = by_zone.get(block.zone_id) if block.zone_id is not None else None
        if limit is None or len(block.text) <= limit:
            out.append(block)
            continue
        # Не влезает и первое слово — остаётся оно: блок не снимается. Пустой текст был бы
        # той самой потерей, от которой уходит план Б (строка 4), а обрубок посреди слова —
        # браком. Кегль такому слову спустит вёрстка, а вызывающий назовёт случай в отчёте:
        # он виден по тому, что осталось знаков больше, чем держит место.
        text = _by_words(block.text)(limit) or block.text.split()[0]
        cut[block.block_id] = (len(block.text), len(text))
        out.append(block.model_copy(update={"text": text}))
    return out, cut
