"""Паспорт слайда-примера (план Б, шаг 1; ADR-009). Change `the-example-passport`.

Каталог композиций (`designsystem/recipes.py`) знает зоны примера и его повторы. Паспорт
добавляет то, без чего нельзя написать текст **под места** и удалить незаполненное
**группой**:

* **группы мест.** Карточка — подложка без текста и тексты, чьи центры в ней лежат
  (вложенность рамок); без подложки — повтор, найденный каталогом; остальное — одиночные
  группы. Декор группы — подложка и фигуры без текста внутри неё. Группы одной формы
  и одного размера — ряд. Картинка примера — своя группа с местом-картинкой (`_drafts`);
* **ёмкость по метрикам шрифта.** Не 0,52 × кегль на знак (`Zone.capacity_chars`), а тем
  же вписыванием, которым колоду будут верстать (`layout.fit_slide`): пробный текст
  растёт, пока встаёт кеглем автора без спуска. Текст, написанный «ровно под место»,
  обязан в место встать — иначе паспорт врёт так же, как 0,52;
* **пробную заливку.** Все места примера заливаются пробным текстом на свою ёмкость
  и вписываются одним слайдом. Не встало или место не держит двух слов — у примера
  паспорта нет, и путь `by_example` его не берёт. Причина называется, а не глотается.

Слой `composition`, а не `designsystem`: мерить шрифтом умеет `layout`, а `designsystem`
стоит ниже него (ARCHITECTURE §3). Модель паспорта — в `designsystem/models.py`, это
данные дизайн-системы; строит её тот, кто умеет мерить.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from itertools import count

from pydantic import ValidationError

from deckforge.designsystem.models import (
    DesignSystem,
    ExamplePassport,
    Place,
    PlaceGroup,
    PlaceKind,
    Recipe,
    TypeLevel,
    Zone,
)
from deckforge.designsystem.recipes import CHAR_WIDTH_RATIO
from deckforge.domain.enums import TextRole
from deckforge.domain.slide import FitResult, SlideIR, TextBlock
from deckforge.domain.template import ExampleShape, TemplateExample, TemplateManifest
from deckforge.domain.units import EMU_PER_PT
from deckforge.layout.by_design import DesignRules
from deckforge.layout.fitting import AS_IS, fit_slide
from deckforge.layout.fonts import FontLibrary

#: Пробный текст: деловая русская проза с обычным разбросом длины слов. Ёмкость места —
#: сколько знаков такого текста встаёт, а не сколько узких «и» или широких «Ш».
SAMPLE_TEXT = (
    "Команда сократила время подготовки отчёта с трёх дней до четырёх часов и перевела "
    "согласование в общий календарь. Доля ошибок в сводных таблицах упала вдвое, а новые "
    "сотрудники выходят на полную нагрузку за две недели вместо месяца. Следующий шаг — "
    "автоматическая проверка исходных данных и единый шаблон для всех подразделений."
)

#: Меньше двух слов место не держит — писать в него нечего. Та же планка, что у раскладки
#: по зонам (`recipe_binding.MIN_WORDS`): зона, куда не встают два слова, кончится снятием.
MIN_WORDS = 2

#: Потолок поиска в долях оценки 0,52 × кегль: оценка грубая, но не в разы.
SEARCH_CEILING = 3

#: Пробное число — для мест, которые двух слов не держат: номер шага, показатель, метка.
#: Автор ставит туда «01», «+12 %», «2024», и мерить их словами прозы значит получить ноль.
SAMPLE_NUMBER = "2024 37,5 % 1 275 +12 "

#: Встаёт ли пробный текст в зоны рецепта: `{zone_id: текст}` → `{zone_id: встал}`.
Fits = Callable[[Recipe, dict[str, str]], dict[str, bool]]


def sample(chars: int) -> str:
    """Пробный текст не длиннее `chars` знаков, целыми словами."""
    pool = SAMPLE_TEXT.split()
    words: list[str] = []
    length = 0
    while True:
        word = pool[len(words) % len(pool)]
        grown = length + (1 if words else 0) + len(word)
        if grown > chars:
            return " ".join(words)
        words.append(word)
        length = grown


def sample_number(chars: int) -> str:
    """Пробное число не длиннее `chars` знаков."""
    text = (SAMPLE_NUMBER * (chars // len(SAMPLE_NUMBER) + 1))[:chars]
    return text.strip()


def _role(zone: Zone) -> TextRole:
    """Роль блока в зоне — как у раскладки по зонам (`recipe_binding`): мерить тем же."""
    return TextRole.TITLE if zone.role is TypeLevel.SLIDE_TITLE else TextRole.BODY


def probe_size(zone: Zone, manifest: TemplateManifest, floor: float) -> float | None:
    """Кегль пробной заливки: тот, которым место будет написано, а не тот, что у автора.

    Автор шаблона набирает подписи и мельче порога читаемости: у VK Tech `ex018` карточки
    подписаны 9 pt при пороге 10 pt — 317 мест из 650 на этом шаблоне. Вёрстка такой текст
    поднимет до порога (план Б, шаг 5а), и место вместит меньше, чем обещал паспорт.
    Обещание исправляется здесь: ниже порога не меряем.

    `None` — мерить кеглем автора, как раньше: он не ниже порога либо неизвестен вовсе.
    """
    if zone.size_pt is None or zone.size_pt >= floor:
        return None
    ladder = [size for size in manifest.size_ladder_pt if size >= floor]
    return min(ladder) if ladder else floor


def _landed(result: FitResult | None) -> bool:
    """Текст встал кеглем автора: без переполнения и без спуска по шкале."""
    return result is not None and not result.overflow and result.strategy == AS_IS


def fit_measure(
    manifest: TemplateManifest, ds: DesignSystem, fonts: FontLibrary | None
) -> Fits:
    """Замер вписыванием колоды (`layout.fit_slide`) — тем, чем слайд будут верстать."""
    rules = DesignRules(manifest, ds)
    layout_id = manifest.layouts[0].layout_id if manifest.layouts else "L01"

    floor = rules.reading_floor_pt

    def fits(recipe: Recipe, texts: dict[str, str]) -> dict[str, bool]:
        zones = {zone.zone_id: zone for zone in recipe.zones}
        filled = {zone_id: text for zone_id, text in texts.items() if text}
        if not filled:
            return dict.fromkeys(texts, True)
        blocks = [
            TextBlock(block_id=f"b{index:02d}", zone_id=zone_id, role=_role(zones[zone_id]),
                      text=text, size_pt=probe_size(zones[zone_id], manifest, floor))
            for index, (zone_id, text) in enumerate(filled.items(), start=1)
        ]
        slide = SlideIR(
            slide_id="s01", layout_id=layout_id, variant="A", blocks=blocks,
            recipe_id=recipe.recipe_id,
        )
        report = fit_slide(slide, manifest, fonts=fonts, design=rules).fit_report
        landed = {block.zone_id: _landed(report.get(block.block_id)) for block in blocks}
        return {zone_id: landed.get(zone_id, True) for zone_id in texts}

    return fits


def capacity(
    recipe: Recipe,
    zone: Zone,
    fits: Fits,
    *,
    ceiling: int,
    make: Callable[[int], str] = sample,
) -> int:
    """Наибольшая длина пробного текста, которая встаёт в зону кеглем автора.

    Двоичный поиск по длине: длиннее не встанет, если не встал короче. Потолок задаёт
    вызывающий (`_ceiling`): у рамки-якоря (D02) высота не ограничивает, и без потолка
    ёмкость была бы бесконечной.
    """

    def ok(chars: int) -> bool:
        return fits(recipe, {zone.zone_id: make(chars)})[zone.zone_id]

    low, high = 0, max(1, ceiling)
    if ok(high):
        return len(make(high))
    while high - low > 1:
        middle = (low + high) // 2
        if ok(middle):
            low = middle
        else:
            high = middle
    return len(make(low))


def _ceiling(zone: Zone, shape: ExampleShape | None) -> int:
    """Сколько знаков вообще искать: больше всего из трёх оценок.

    * тройная оценка 0,52 × кегль — у рамки, которая держит строки своего кегля;
    * одна строка по ширине рамки — у рамки-якоря (D02) оценка 0,52 равна нулю, хотя
      строка в ней встаёт: заголовок WorkSpace 60 pt в полосе 0,5 см;
    * длина текста самого автора — он уже решил, сколько сюда пишется.
    """
    line = 0
    if zone.cx and zone.size_pt:
        line = int(zone.cx / (zone.size_pt * CHAR_WIDTH_RATIO * EMU_PER_PT))
    author = shape.text_len if shape is not None else 0
    return max(zone.capacity_chars * SEARCH_CEILING, line, author)


#: Фигура больше этой доли слайда — фон, а не подложка карточки: иначе все тексты
#: слайда собрались бы в одну группу «под фоном».
CONTAINER_MAX_SHARE = 0.5

#: Допуск на размер подложек одного ряда, доля размера. Тот же порядок, что допуск ячейки
#: в каталоге композиций (`recipes.CELL_TOLERANCE`).
SAME_SIZE_TOLERANCE = 0.1


def _contains(outer: ExampleShape, inner: ExampleShape) -> bool:
    """Центр `inner` лежит в рамке `outer`."""
    cx, cy = inner.x + inner.cx // 2, inner.y + inner.cy // 2
    return outer.x <= cx <= outer.x + outer.cx and outer.y <= cy <= outer.y + outer.cy


def _area(shape: ExampleShape) -> int:
    return shape.cx * shape.cy


def _same_size(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    if a is None or b is None:
        return False
    return (
        abs(a[0] - b[0]) <= a[0] * SAME_SIZE_TOLERANCE
        and abs(a[1] - b[1]) <= a[1] * SAME_SIZE_TOLERANCE
    )


def _frame(shapes: list[ExampleShape]) -> dict[str, int | None]:
    """Общая рамка фигур группы; пусто — рамки нет."""
    if not shapes:
        return {"x": None, "y": None, "cx": None, "cy": None}
    left = min(s.x for s in shapes)
    top = min(s.y for s in shapes)
    right = max(s.x + s.cx for s in shapes)
    bottom = max(s.y + s.cy for s in shapes)
    return {"x": left, "y": top, "cx": right - left, "cy": bottom - top}


@dataclass
class _Draft:
    """Группа до нумерации мест: тексты, декор, рамка и размер для сверки ряда."""

    zones: list[Zone]
    decor: list[int]
    frame: dict[str, int | None]
    #: Размер, по которому группа сверяется с соседями ряда; `None` — в ряд не идёт.
    size: tuple[int, int] | None

    @property
    def top_left(self) -> tuple[int, int]:
        return self.frame["y"] or 0, self.frame["x"] or 0


def _drafts(recipe: Recipe, example: TemplateExample, slide_area: int) -> list[_Draft]:
    """Группы мест примера (план Б, шаг 1): по подложкам, потом по повторам каталога.

    **Подложка.** Карточка шаблона — фигура без текста и тексты, чьи центры в ней лежат.
    В VK Tech карточки не сгруппированы `p:grpSp` — это плоские фигуры, и искать группу
    в XML бесполезно; подложка же есть. Текст берёт самую маленькую подложку, в которой
    **два и больше текстов**: у заголовка карточки своя плашка-полоска, и «просто самая
    маленькая» разрезала бы карточку пополам (VK Tech `ex018`). Нет такой — свою плашку.
    Фон на пол-слайда подложкой не считается. Декор — подложка и всё без текста, чей
    центр в ней лежит и не лежит в меньшей подложке другой группы.

    **Повтор каталога.** Карточка без подложки (текст и линия, текст и иконка сбоку) —
    группа по повтору, который нашёл каталог (`Recipe.repeat_xml_ids`). Он ошибается
    на сетках — ряд принимает за карточку, — поэтому идёт вторым, после подложек.

    Остальное — одиночные группы.
    """
    text_xml = {zone.xml_id for zone in recipe.zones if zone.xml_id is not None}
    by_xml = {shape.xml_id: shape for shape in example.shapes if shape.xml_id is not None}
    texts = [by_xml[z.xml_id] for z in recipe.zones if z.xml_id in by_xml]
    blanks = [
        shape for shape in example.shapes
        if shape.xml_id is not None
        and shape.xml_id not in text_xml
        and shape.xml_id != recipe.picture_xml_id
        and _area(shape) < slide_area * CONTAINER_MAX_SHARE
    ]
    holds = {id(b): sum(1 for text in texts if _contains(b, text)) for b in blanks}

    def container_of(text: ExampleShape) -> ExampleShape | None:
        under = [b for b in blanks if b.z < text.z and _contains(b, text)]
        shared = [b for b in under if holds[id(b)] >= 2]
        pool = shared or under
        return min(pool, key=_area) if pool else None

    by_container: dict[int, list[Zone]] = {}
    rest: list[Zone] = []
    for zone in recipe.zones:
        text = by_xml.get(zone.xml_id) if zone.xml_id is not None else None
        box = container_of(text) if text is not None else None
        if box is None or box.xml_id is None:
            rest.append(zone)
        else:
            by_container.setdefault(box.xml_id, []).append(zone)

    containers = [by_xml[xml_id] for xml_id in by_container]
    drafts: list[_Draft] = []
    taken: set[int] = set()
    for box in containers:
        decor = [
            b.xml_id for b in blanks
            if b.xml_id is not None and (b is box or (
                _contains(box, b)
                and _area(b) < _area(box)
                and not any(o is not box and _area(o) < _area(box) and _contains(o, b)
                            for o in containers)
            ))
        ]
        taken.update(decor)
        zones = _reading_order(by_container[box.xml_id or 0])
        frame = _frame([box, *(by_xml[z.xml_id] for z in zones if z.xml_id in by_xml)])
        drafts.append(_Draft(zones, decor, frame, (box.cx, box.cy)))

    by_repeat: dict[int, list[Zone]] = {}
    alone: list[Zone] = []
    for zone in rest:
        if zone.repeat is not None and zone.repeat < len(recipe.repeat_xml_ids):
            by_repeat.setdefault(zone.repeat, []).append(zone)
        else:
            alone.append(zone)
    for index, zones in sorted(by_repeat.items()):
        addresses = recipe.repeat_xml_ids[index]
        decor = [a for a in addresses if a not in text_xml and a not in taken]
        taken.update(decor)
        frame = _frame([by_xml[a] for a in addresses if a in by_xml])
        size = (frame["cx"] or 0, frame["cy"] or 0)
        drafts.append(_Draft(_reading_order(zones), decor, frame, size))

    for zone in alone:
        frame = {"x": zone.x, "y": zone.y, "cx": zone.cx, "cy": zone.cy}
        drafts.append(_Draft([zone], [], frame, None))
    return sorted(drafts, key=lambda d: d.top_left)


def _reading_order(zones: Iterable[Zone]) -> list[Zone]:
    return sorted(zones, key=lambda zone: (zone.y or 0, zone.x or 0, zone.zone_id))


def build_passport(
    recipe: Recipe, example: TemplateExample, fits: Fits, *, slide_area: int
) -> ExamplePassport | str:
    """Паспорт примера или причина, почему его нет."""
    by_xml = {shape.xml_id: shape for shape in example.shapes if shape.xml_id is not None}
    places = count(1)

    def place(zone: Zone) -> Place | str:
        """Место под прозу, если держит два слова; иначе — под число или метку."""
        shape = by_xml.get(zone.xml_id) if zone.xml_id is not None else None
        ceiling = _ceiling(zone, shape)
        chars = capacity(recipe, zone, fits, ceiling=ceiling)
        kind = PlaceKind.TEXT
        if len(sample(chars).split()) < MIN_WORDS:
            kind = PlaceKind.NUMBER
            chars = capacity(recipe, zone, fits, ceiling=ceiling, make=sample_number)
        if chars == 0:
            return f"зона {zone.zone_id} не держит и одного знака кеглем автора"
        return Place(
            place_id=f"p{next(places):02d}", kind=kind, zone_id=zone.zone_id,
            xml_id=zone.xml_id, role=zone.role, capacity_chars=chars,
        )

    drafts = _drafts(recipe, example, slide_area)
    groups: list[PlaceGroup] = []
    for index, draft in enumerate(drafts, start=1):
        made: list[Place] = []
        for zone in draft.zones:
            one = place(zone)
            if isinstance(one, str):
                return one
            made.append(one)
        groups.append(PlaceGroup(
            group_id=f"g{index:02d}", places=made,
            decor_xml_ids=sorted(draft.decor),
            **draft.frame,
        ))
    groups = _rows(groups, [draft.size for draft in drafts])

    if recipe.has_picture and recipe.picture_xml_id is not None:
        picture = by_xml.get(recipe.picture_xml_id)
        groups.append(PlaceGroup(
            group_id=f"g{len(groups) + 1:02d}",
            places=[Place(place_id=f"p{next(places):02d}", kind=PlaceKind.PICTURE,
                          xml_id=recipe.picture_xml_id)],
            **_frame([picture] if picture is not None else []),
        ))

    try:
        passport = ExamplePassport(groups=groups)
    except ValidationError as error:
        return f"паспорт не сложился: {error.errors()[0]['msg']}"
    return _trial_fill(recipe, passport, fits) or passport


def _rows(groups: list[PlaceGroup], sizes: list[tuple[int, int] | None]) -> list[PlaceGroup]:
    """Ряды — группы одной формы и одного размера, от двух штук.

    Форма — виды и ступени мест по порядку (`PlaceGroup.shape`): только такие группы
    композиция заполнит повтором «N × (подзаголовок, текст)». Ряд не обязан лежать
    на одной линии: сетка 3 + 2 карточки VK Tech — один ряд из пяти.
    """
    rows: list[list[int]] = []
    for index, (group, size) in enumerate(zip(groups, sizes, strict=True)):
        if size is None:
            continue
        for row in rows:
            head = row[0]
            if groups[head].shape == group.shape and _same_size(sizes[head], size):
                row.append(index)
                break
        else:
            rows.append([index])
    names = {
        index: f"r{number}"
        for number, row in enumerate((r for r in rows if len(r) >= 2), start=1)
        for index in row
    }
    return [
        group.model_copy(update={"row": names[index]}) if index in names else group
        for index, group in enumerate(groups)
    ]


def _trial_fill(recipe: Recipe, passport: ExamplePassport, fits: Fits) -> str | None:
    """Все места разом на свою ёмкость: не встало хоть одно — причина, встали все — `None`.

    Места мерились по одному, а верстаются вместе: заголовок уступает кегль соседям
    (`_titles_yield_size`), и то, что встало в одиночку, в полном слайде может не встать.
    """
    texts = {
        place.zone_id: (sample if place.kind is PlaceKind.TEXT else sample_number)(
            place.capacity_chars
        )
        for place in passport.places
        if place.zone_id is not None
    }
    landed = fits(recipe, texts)
    failed = sorted(zone_id for zone_id, ok in landed.items() if not ok)
    return f"пробная заливка: не встали зоны {failed}" if failed else None


@dataclass
class PassportReport:
    """Итог по каталогу: у кого паспорт есть и почему у остальных его нет."""

    with_passport: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)

    def notes(self) -> list[str]:
        return [f"паспорт {rid}: нет — {why}" for rid, why in sorted(self.rejected.items())]


def with_passports(
    ds: DesignSystem, manifest: TemplateManifest, fonts: FontLibrary | None = None,
    *, fits: Fits | None = None,
) -> tuple[DesignSystem, PassportReport]:
    """Дизайн-система, где у каждого рецепта, который прошёл пробную заливку, есть паспорт."""
    measure = fits or fit_measure(manifest, ds, fonts)
    examples = {example.slide_index: example for example in manifest.examples}
    slide_area = ds.grid.width_emu * ds.grid.height_emu
    report = PassportReport()
    recipes: list[Recipe] = []
    for recipe in ds.recipes:
        example = examples.get(recipe.example_index)
        made = (
            build_passport(recipe, example, measure, slide_area=slide_area)
            if example is not None
            else f"примера №{recipe.example_index} нет в манифесте"
        )
        if isinstance(made, str):
            report.rejected[recipe.recipe_id] = made
            recipes.append(recipe.model_copy(update={"passport": None}))
        else:
            report.with_passport.append(recipe.recipe_id)
            # `model_validate`, а не `model_copy`: копия валидаторы не запускает, и место
            # на чужой зоне прошло бы молча.
            recipes.append(Recipe.model_validate(
                recipe.model_dump() | {"passport": made.model_dump()}
            ))
    return ds.model_copy(update={"recipes": recipes}), report
