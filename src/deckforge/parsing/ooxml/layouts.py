"""Плейсхолдеры с каскадом slideMaster → slideLayout. Change (3) `template-parsing-core`.

Правило наследования OOXML: плейсхолдер макета берёт геометрию у одноимённого плейсхолдера
мастера, если своей не задал. В реальных шаблонах встречается и обратное — мастер пуст,
а вся геометрия лежит в макетах, поэтому отсутствие мастера не является ошибкой.
"""

from __future__ import annotations

from lxml import etree

from deckforge.domain.enums import TextRole
from deckforge.domain.template import LayoutShape, PlaceholderSpec, ShapeKind
from deckforge.domain.units import EMU_PER_PT

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"

#: Тип плейсхолдера OOXML → роль в типографической шкале.
#: Роли — наши, типы — из стандарта, поэтому сопоставление здесь, а не в домене.
ROLE_BY_PH_TYPE: dict[str, TextRole] = {
    "title": TextRole.TITLE,
    "ctrTitle": TextRole.TITLE,
    "subTitle": TextRole.SUBTITLE,
    "body": TextRole.BODY,
    "obj": TextRole.BODY,
    "tbl": TextRole.BODY,
    "chart": TextRole.BODY,
    "ftr": TextRole.CAPTION,
    "sldNum": TextRole.CAPTION,
    "dt": TextRole.CAPTION,
}

#: Плейсхолдеры, которые не несут контента колоды: их присутствие не делает макет
#: «содержательным». Хранятся в нижнем регистре, потому что сверка идёт и с типом
#: из XML (`sldNum`), и с нормализованным типом манифеста (`SLDNUM`).
DECOR_PH_TYPES = frozenset({"ftr", "sldnum", "dt"})


class RawPlaceholder:
    """Плейсхолдер как он лежит в XML: геометрия может быть не задана."""

    __slots__ = ("bold", "cx", "cy", "font", "idx", "ph_type", "size_pt", "x", "y")

    def __init__(
        self,
        idx: int,
        ph_type: str,
        x: int | None,
        y: int | None,
        cx: int | None,
        cy: int | None,
        size_pt: float | None,
        bold: bool | None,
        font: str | None = None,
    ) -> None:
        self.idx = idx
        self.ph_type = ph_type
        self.x, self.y, self.cx, self.cy = x, y, cx, cy
        self.size_pt = size_pt
        self.bold = bold
        self.font = font

    @property
    def key(self) -> tuple[str, int]:
        """Ключ наследования: тип плюс индекс. Титул без idx — это idx=0."""
        return (self.ph_type, self.idx)

    @property
    def has_geometry(self) -> bool:
        return None not in (self.x, self.y, self.cx, self.cy)


def _text_properties(
    shape: etree._Element,
) -> tuple[float | None, bool | None, str | None]:
    """Кегль, жирность и гарнитура первого уровня из `lvl1pPr/defRPr`.

    Именно здесь в шаблонах, выгруженных из сторонних редакторов, лежат настоящие размеры:
    `txStyles` мастера у них заполнены одинаковым значением для всех уровней и бесполезны.

    Гарнитура возвращается как есть, вместе со ссылками вида `+mj-lt`: разрешать их
    некому — тема известна на уровень выше, в сборщике манифеста.
    """
    for xpath in (
        f".//{{{A}}}lvl1pPr/{{{A}}}defRPr",
        f".//{{{A}}}defRPr",
        f".//{{{A}}}rPr",
    ):
        node = shape.find(xpath)
        if node is None:
            continue
        raw_size = node.get("sz")
        if raw_size:
            bold = node.get("b")
            latin = node.find(f"{{{A}}}latin")
            typeface = (latin.get("typeface") if latin is not None else None) or None
            return int(raw_size) / 100, (bold == "1") if bold is not None else None, typeface
    return None, None, None


#: Стиль мастера по типу плейсхолдера — последняя ступень каскада OOXML. Размер из
#: `p:txStyles` действует тогда, когда его не объявили ни фигура макета, ни фигура мастера.
#: Шаблоны, собранные не в PowerPoint, держат кегли только здесь.
_TX_STYLE_BY_PH_TYPE: dict[str, str] = {
    "title": "titleStyle",
    "ctrTitle": "titleStyle",
    "body": "bodyStyle",
    "subTitle": "bodyStyle",
    "obj": "bodyStyle",
    "tbl": "bodyStyle",
    "chart": "bodyStyle",
}
_DEFAULT_TX_STYLE = "otherStyle"


def parse_text_styles(master_xml: bytes) -> dict[str, tuple[float | None, bool | None, str | None]]:
    """Кегль, жирность и гарнитура первого уровня из `p:txStyles` мастера.

    Это не то же самое, что фигуры мастера: `txStyles` — стиль по умолчанию для роли,
    и в шаблонах, где фигуры размеров не объявляют, он единственный источник правды.
    """
    root = etree.fromstring(master_xml)
    styles = root.find(f".//{{{P}}}txStyles")
    if styles is None:
        return {}

    out: dict[str, tuple[float | None, bool | None, str | None]] = {}
    for style in styles:
        name = etree.QName(style).localname
        props = style.find(f"{{{A}}}lvl1pPr/{{{A}}}defRPr")
        if props is None or not props.get("sz"):
            continue
        bold = props.get("b")
        latin = props.find(f"{{{A}}}latin")
        out[name] = (
            int(props.get("sz")) / 100,
            (bold == "1") if bold is not None else None,
            (latin.get("typeface") if latin is not None else None) or None,
        )
    return out


def parse_placeholders(part_xml: bytes) -> list[RawPlaceholder]:
    """Плейсхолдеры одной части (мастера или макета) без разрешения наследования."""
    root = etree.fromstring(part_xml)
    out: list[RawPlaceholder] = []

    for shape in root.iter(f"{{{P}}}sp"):
        ph = shape.find(f".//{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
        if ph is None:
            continue
        # У титула атрибуты type и idx часто опущены: по стандарту это body и idx=0.
        ph_type = ph.get("type") or "body"
        idx = int(ph.get("idx") or 0)

        off = shape.find(f".//{{{A}}}xfrm/{{{A}}}off")
        ext = shape.find(f".//{{{A}}}xfrm/{{{A}}}ext")
        size_pt, bold, font = _text_properties(shape)
        out.append(
            RawPlaceholder(
                idx=idx,
                ph_type=ph_type,
                x=int(off.get("x")) if off is not None else None,
                y=int(off.get("y")) if off is not None else None,
                cx=int(ext.get("cx")) if ext is not None else None,
                cy=int(ext.get("cy")) if ext is not None else None,
                size_pt=size_pt,
                bold=bold,
                font=font,
            )
        )
    return out


def resolve_placeholders(
    layout_xml: bytes, master_xml: bytes | None = None
) -> list[PlaceholderSpec]:
    """Плейсхолдеры макета с разрешённым наследованием от мастера.

    Плейсхолдер без геометрии и без пары в мастере отбрасывается: положить его на слайд
    всё равно некуда, а выдумывать координаты — ровно то, что запрещает C6.
    """
    inherited: dict[tuple[str, int], RawPlaceholder] = {}
    styles: dict[str, tuple[float | None, bool | None, str | None]] = {}
    if master_xml:
        inherited = {ph.key: ph for ph in parse_placeholders(master_xml)}
        styles = parse_text_styles(master_xml)

    specs: list[PlaceholderSpec] = []
    for ph in parse_placeholders(layout_xml):
        base = inherited.get(ph.key)
        style_size, style_bold, style_font = styles.get(
            _TX_STYLE_BY_PH_TYPE.get(ph.ph_type, _DEFAULT_TX_STYLE), (None, None, None)
        )
        x = ph.x if ph.x is not None else (base.x if base else None)
        y = ph.y if ph.y is not None else (base.y if base else None)
        cx = ph.cx if ph.cx is not None else (base.cx if base else None)
        cy = ph.cy if ph.cy is not None else (base.cy if base else None)
        if x is None or y is None or not cx or not cy:
            continue

        specs.append(
            PlaceholderSpec(
                idx=ph.idx,
                ph_type=ph.ph_type.upper(),
                role=ROLE_BY_PH_TYPE.get(ph.ph_type),
                x=max(0, x),
                y=max(0, y),
                cx=cx,
                cy=cy,
                # Наследуются так же, как геометрия, и на ступень глубже: своя фигура,
                # затем фигура мастера, затем `txStyles` мастера. Без последней ступени
                # кегль остаётся пустым на шаблонах, где размеры объявлены только там.
                font_family=_first(ph.font, base.font if base else None, style_font),
                size_pt=_first(ph.size_pt, base.size_pt if base else None, style_size),
                bold=_first(ph.bold, base.bold if base else None, style_bold),
            )
        )

    # Дубли по idx делают SlideIR.placeholder_idx неоднозначным; оставляем первый.
    seen: set[int] = set()
    unique: list[PlaceholderSpec] = []
    for spec in sorted(specs, key=lambda s: (s.idx, s.y, s.x)):
        if spec.idx not in seen:
            seen.add(spec.idx)
            unique.append(spec)
    return _title_band(unique)


#: Во сколько строк своего кегля укладывается полоса заголовка. Две — с запасом
#: на межстрочный интервал: полоса в полторы строки — всё ещё одна строка.
_TITLE_BAND_LINES = 2.0

#: Высота строки в долях кегля — та же, что у мерила вместимости.
_LINE_RATIO = 1.2


def _title_band(specs: list[PlaceholderSpec]) -> list[PlaceholderSpec]:
    """Полоса заголовка, размеченная плейсхолдером body, получает роль заголовка.

    «Шаблон презентации 2024» не держит в макетах title вовсе: заголовок у него — body
    высотой 1,4 см над телом, набранный 32 pt. Для конвейера это было место под текст:
    композитор клал туда список восьмым кеглем, заголовка на слайде не было, а тело
    оставалось пустым (прогон ad29e1b6f77e, пустая полоса 81 % высоты на 8 слайдах).

    Признаки берутся из самого макета, а не из имени шаблона (C6): заголовка нет,
    полоса — самая верхняя из body, высотой в строку своего кегля, и кегль у неё
    крупнее, чем у любого другого body макета.
    """
    if any(spec.role is TextRole.TITLE for spec in specs):
        return specs
    bodies = [spec for spec in specs if spec.role is TextRole.BODY and spec.size_pt]
    if len(bodies) < 2:
        return specs
    top = min(bodies, key=lambda spec: spec.y)
    others = [spec for spec in bodies if spec is not top]
    size = top.size_pt or 0.0
    one_line = top.cy <= _TITLE_BAND_LINES * _LINE_RATIO * size * EMU_PER_PT
    largest = all(size > (spec.size_pt or 0.0) for spec in others)
    above = all(top.y + top.cy <= spec.y for spec in others)
    if not (one_line and largest and above):
        return specs
    return [
        spec.model_copy(update={"role": TextRole.TITLE}) if spec is top else spec
        for spec in specs
    ]


def _first[T](*values: T | None) -> T | None:
    """Первое объявленное значение каскада. `None` значит «не объявлено», а не «ноль»."""
    return next((value for value in values if value is not None), None)


def placeholder_text_sizes(
    layout_xml: bytes, master_xml: bytes | None = None
) -> dict[int, tuple[float | None, bool | None]]:
    """Наблюдаемые кегль и жирность по idx плейсхолдера — вход для вывода типошкалы."""
    inherited: dict[tuple[str, int], RawPlaceholder] = {}
    if master_xml:
        inherited = {ph.key: ph for ph in parse_placeholders(master_xml)}

    out: dict[int, tuple[float | None, bool | None]] = {}
    for ph in parse_placeholders(layout_xml):
        base = inherited.get(ph.key)
        size = ph.size_pt if ph.size_pt is not None else (base.size_pt if base else None)
        bold = ph.bold if ph.bold is not None else (base.bold if base else None)
        out.setdefault(ph.idx, (size, bold))
    return out


#: Минимальная доля площади слайда, ниже которой фигура для классификации не интересна:
#: мелкий декор только зашумит схему и промпт.
_MIN_SHAPE_AREA_SHARE = 0.01

_KIND_BY_TAG = {
    "pic": ShapeKind.PICTURE,
    "graphicFrame": ShapeKind.CHART,
    "tbl": ShapeKind.TABLE,
}


def parse_shapes(part_xml: bytes, slide_cx: int, slide_cy: int) -> list[LayoutShape]:
    """Фигуры вне плейсхолдеров: фон, фотографии, декоративные знаки.

    В шаблонах это сплошь и рядом: в «Паттерн + фото» фотография лежит элементом `p:pic`
    без всякого плейсхолдера, и макет, разобранный по одним плейсхолдерам, выглядит как
    пустой слайд с заголовком.

    Группы разворачиваются: внутри `p:grpSp` встречаются те же картинки.
    """
    root = etree.fromstring(part_xml)
    tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree")
    if tree is None:
        return []

    slide_area = slide_cx * slide_cy
    shapes: list[LayoutShape] = []
    _collect_shapes(tree, shapes, slide_area, prefix="s")
    return shapes


def _collect_shapes(
    parent: etree._Element, out: list[LayoutShape], slide_area: int, prefix: str
) -> None:
    for index, element in enumerate(parent):
        tag = etree.QName(element).localname
        if tag in ("nvGrpSpPr", "grpSpPr"):
            continue
        if tag == "grpSp":
            _collect_shapes(element, out, slide_area, prefix=f"{prefix}{index}g")
            continue
        if tag not in ("sp", "pic", "graphicFrame"):
            continue
        if element.find(f".//{{{P}}}nvPr/{{{P}}}ph") is not None:
            continue  # плейсхолдеры разбираются отдельно

        off = element.find(f".//{{{A}}}xfrm/{{{A}}}off")
        ext = element.find(f".//{{{A}}}xfrm/{{{A}}}ext")
        if off is None or ext is None:
            continue
        try:
            cx, cy = int(ext.get("cx")), int(ext.get("cy"))
            x, y = int(off.get("x")), int(off.get("y"))
        except (TypeError, ValueError):
            continue
        if cx <= 0 or cy <= 0 or (slide_area and cx * cy / slide_area < _MIN_SHAPE_AREA_SHARE):
            continue

        text = "".join(element.itertext()).strip()
        kind = _KIND_BY_TAG.get(tag, ShapeKind.TEXT if text else ShapeKind.SHAPE)
        if tag == "graphicFrame" and element.find(f".//{{{A}}}tbl") is not None:
            kind = ShapeKind.TABLE

        out.append(
            LayoutShape(
                shape_id=f"{prefix}{index}",
                kind=kind,
                # Фигуры за краем слайда (гигантская кавычка на y=-1 млн) обрезаются,
                # но не выбрасываются: видимая часть и есть то, что читает человек.
                x=max(0, x),
                y=max(0, y),
                cx=cx,
                cy=cy,
                z=index,
                text=text[:40] or None,
            )
        )
