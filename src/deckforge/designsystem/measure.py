"""Измеренное по слайдам-примерам: роли цветов, доли, сочетания, контрасты, гарнитуры.

Роль цвета выводится из **доли площади**, а не из частоты появления: `usage.palette`
считает, сколько раз цвет встретился, и девятнадцать литералов одного шаблона при этом
равны между собой. Подложка на половину слайда весит больше, чем шесть подписей, — и
только площадь это показывает.

Сигнатура `measure(manifest, ds) -> DesignSystem` фиксирована: на ней держится
параллельная волна, и `derive.py` её уже вызывает.
"""

from __future__ import annotations

from collections import defaultdict

from deckforge.designsystem.contrast import (
    COMFORT_CAPTION,
    MIN_BODY,
    TextClass,
    readability,
)
from deckforge.designsystem.models import (
    ColorRoleKind,
    Combination,
    ComponentCard,
    ContrastLevel,
    ContrastPair,
    DesignSystem,
    FontInUse,
    NumberScale,
    Origin,
    PaletteRole,
)
from deckforge.domain.enums import ColorRef
from deckforge.domain.rules import (
    TEXT_SLOTS,
    contrast_ratio,
    delta_e_rgb,
    meets_wcag_aa,
    next_size_down,
    relative_luminance,
)
from deckforge.domain.template import (
    ComponentKind,
    ExampleShape,
    TemplateExample,
    TemplateManifest,
    Theme,
)

#: Сколько знаков после запятой хранится у долей. Доли попадают в разметку страницы,
#: а она обязана быть побайтно одинаковой от прогона к прогону (G01). То же число, что
#: у долей в `derive.py`: импортировать его оттуда нельзя — `derive` импортирует нас.
SHARE_DIGITS = 6

#: Насыщенность, с которой цвет считается акцентом: разброс каналов RGB в долях от
#: полного. Порог алгоритма, а не константа шаблона: серый с долей в четыре процента —
#: это разделители и подписи, а не акцент, и отличает их от акцента именно разброс
#: каналов, одинаково на любом шаблоне.
ACCENT_SATURATION = 0.15

#: Знаков после запятой у коэффициента контраста: на странице он читается как «4,81»,
#: и лишние знаки только мешают.
RATIO_DIGITS = 2

#: Пары схемы OOXML: тёмный слот на своём светлом и обратно. Это те пары, которые тема
#: объявляет сама, — провал любой из них означает, что шаблон противоречит себе.
SCHEME_PAIRS: tuple[tuple[ColorRef, ColorRef], ...] = (
    (ColorRef.DK1, ColorRef.LT1),
    (ColorRef.LT1, ColorRef.DK1),
    (ColorRef.DK2, ColorRef.LT2),
    (ColorRef.LT2, ColorRef.DK2),
)

#: Слоты, которыми красят графику и метки, а не абзацы. Провал такого слота — не
#: противоречие темы, а граница применимости, и отмечается он отдельно.
ACCENT_SLOTS: tuple[ColorRef, ...] = (
    ColorRef.ACCENT1,
    ColorRef.ACCENT2,
    ColorRef.ACCENT3,
    ColorRef.ACCENT4,
    ColorRef.ACCENT5,
    ColorRef.ACCENT6,
    ColorRef.HLINK,
    ColorRef.FOL_HLINK,
)

#: Доля площади, ниже которой цвет уходит в «редкое» и акцентом уже не считается.
#: Порог алгоритма: у шаблонов кейса фигуры закрывают около десятой части площади,
#: и акцент в тысячную долю — это засечка на одном слайде, а не решение о цвете.
RARE_SHARE = 0.001

#: Какую долю площади показывают цветами по отдельности. Остальное сворачивается
#: в одну запись: у шаблона кейса девятнадцать литералов, и без свёртки раздел
#: превращается в простыню.
TAIL_COVERAGE = 0.95

#: Сколько цветов раздел показывает по отдельности, считая свёрнутый хвост. Потолок
#: нужен и сверх покрытия: акценты шаблона лежат далеко за 95 % площади — фон один
#: закрывает почти всю, — и без потолка они утащили бы в раздел весь список.
SHOWN_LIMIT = 10

#: Сколько сочетаний раздел показывает по отдельности. Потолок того же порядка, что
#: у палитры, и нужен по той же причине: у шаблона кейса троек двадцать семь, и хвост
#: из них — тройки, встреченные на одном слайде из полусотни. Такая тройка описывает
#: слайд, а не шаблон, и в раздел идёт суммой, а не строкой.
COMBINATIONS_SHOWN = 8


def _channels(color_hex: str) -> tuple[int, int, int]:
    h = color_hex.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _saturation(color_hex: str) -> float:
    """Разброс каналов в долях от полного: у серого — ноль, у чистого цвета — единица."""
    red, green, blue = _channels(color_hex)
    return (max(red, green, blue) - min(red, green, blue)) / 0xFF


def _nearest_ref(theme: Theme, color_hex: str) -> ColorRef:
    """Ближайший слот темы по расстоянию в RGB — тем же способом, что `parsing.usage`."""
    return min(ColorRef, key=lambda ref: delta_e_rgb(color_hex, theme.colors.get(ref)))


def _fill_hex(shape: ExampleShape, theme: Theme) -> str | None:
    """Цвет заливки фигуры: слот темы разрешается в цвет, литерал берётся как есть."""
    if shape.fill_ref is not None:
        return theme.colors.get(shape.fill_ref)
    return shape.fill_hex


def _text_hex(shape: ExampleShape, theme: Theme) -> str | None:
    if shape.color_ref is not None:
        return theme.colors.get(shape.color_ref)
    return shape.color_hex


def _background_hex(manifest: TemplateManifest, example: TemplateExample) -> str | None:
    """Фон макета, на котором стоит пример. Пусто — манифест снят до change (24)."""
    if example.layout_id is None:
        return None
    layout = manifest.layout(example.layout_id)
    if layout is None or layout.background is None:
        return None
    return layout.background.color_hex


def _areas(manifest: TemplateManifest) -> tuple[dict[str, int], dict[str, set[int]]]:
    """Площадь каждого цвета по всем примерам и слайды, где он встречен.

    Площадь фигуры отходит её заливке, а у фигуры без заливки — цвету её текста:
    подпись без плашки красит собой ровно то место, где стоит. Непокрытая фигурами
    площадь отходит фону макета. Перекрытия фигур площадь фона занижают — это дешевле,
    чем строить растр: роль цвета решается порядком долей, а не третьим знаком.
    """
    theme = manifest.theme
    slide_area = manifest.slide_size.cx_emu * manifest.slide_size.cy_emu
    areas: dict[str, int] = defaultdict(int)
    seen: dict[str, set[int]] = defaultdict(set)

    for example in manifest.examples:
        covered = 0
        for shape in example.shapes:
            area = shape.cx * shape.cy
            covered += area
            color = _fill_hex(shape, theme) or _text_hex(shape, theme)
            if color is None:
                continue
            areas[color.upper()] += area
            seen[color.upper()].add(example.slide_index)
        background = _background_hex(manifest, example)
        if background is None:
            continue
        areas[background.upper()] += max(0, slide_area - covered)
        seen[background.upper()].add(example.slide_index)

    return areas, seen


def _role(index: int, share: float, color_hex: str) -> ColorRoleKind:
    """Первый по доле — фон, второй — доминанта, дальше акценты и редкие."""
    if index == 0:
        return ColorRoleKind.BACKGROUND
    if index == 1:
        return ColorRoleKind.DOMINANT
    if share >= RARE_SHARE and _saturation(color_hex) >= ACCENT_SATURATION:
        return ColorRoleKind.ACCENT
    return ColorRoleKind.RARE


def _pick(roles: list[PaletteRole], limit: int) -> list[PaletteRole]:
    """Цвета, показанные по отдельности: покрытие площади, затем акценты, но не больше
    потолка. Акценты добираются отдельно: они всегда за границей покрытия, потому что
    фон один закрывает почти всю площадь, — а роль их от этого не меняется."""
    covering: list[PaletteRole] = []
    rest: list[PaletteRole] = []
    covered = 0.0
    for role in roles:
        (covering if covered < TAIL_COVERAGE else rest).append(role)
        covered += role.share

    kept = covering[:limit]
    for role in rest:
        if len(kept) >= limit:
            break
        if role.role is ColorRoleKind.ACCENT:
            kept.append(role)
    return kept


def _collapse_tail(roles: list[PaletteRole]) -> list[PaletteRole]:
    """Свернуть всё, что за пределами покрытия и потолка, в одну запись «ещё N оттенков».

    Запись хвоста занимает место в разделе наравне с цветом, поэтому, когда сворачивать
    есть что, показанных цветов становится на один меньше: иначе потолок раздела
    переполняется ровно на эту запись.
    """
    kept = _pick(roles, SHOWN_LIMIT)
    collapsed = [role for role in roles if role not in kept]
    if not collapsed:
        return kept

    kept = _pick(roles, SHOWN_LIMIT - 1)
    collapsed = [role for role in roles if role not in kept]
    return [
        *kept,
        PaletteRole(
            role=ColorRoleKind.TAIL,
            #: Образец записи — самый крупный из свёрнутых: показать хвост нечем, кроме
            #: одного из его цветов.
            color_hex=collapsed[0].color_hex,
            nearest_ref=collapsed[0].nearest_ref,
            share=round(sum(role.share for role in collapsed), SHARE_DIGITS),
            count=len(collapsed),
            label=f"ещё {len(collapsed)} оттенков",
            origin=Origin.MEASURED,
        ),
    ]


def _palette_roles(manifest: TemplateManifest) -> list[PaletteRole]:
    areas, seen = _areas(manifest)
    total = sum(areas.values())
    if total == 0:
        return []

    ordered = sorted(areas.items(), key=lambda item: (-item[1], item[0]))
    roles = [
        PaletteRole(
            role=_role(index, area / total, color_hex),
            color_hex=color_hex,
            nearest_ref=_nearest_ref(manifest.theme, color_hex),
            share=round(area / total, SHARE_DIGITS),
            seen_on=sorted(seen[color_hex]),
            origin=Origin.MEASURED,
        )
        for index, (color_hex, area) in enumerate(ordered)
    ]
    return _collapse_tail(roles)


def _noticeable_fill(example: TemplateExample, theme: Theme, background_hex: str) -> str | None:
    """Самая заметная заливка слайда, отличная от фона.

    Заметность — сперва насыщенность, потом площадь: бледная подложка занимает больше
    места, но сочетание слайда держится на цветном пятне, а не на ней.
    """
    fills: dict[str, int] = defaultdict(int)
    for shape in example.shapes:
        color = _fill_hex(shape, theme)
        if color is None or color.upper() == background_hex.upper():
            continue
        fills[color.upper()] += shape.cx * shape.cy
    if not fills:
        return None
    return max(
        fills, key=lambda color: (_saturation(color) >= ACCENT_SATURATION, fills[color], color)
    )


def _largest_text(example: TemplateExample, theme: Theme) -> str | None:
    """Цвет текста, занявший на слайде больше всего места."""
    texts: dict[str, int] = defaultdict(int)
    for shape in example.shapes:
        color = _text_hex(shape, theme)
        if color is None:
            continue
        texts[color.upper()] += shape.cx * shape.cy
    if not texts:
        return None
    return max(texts, key=lambda color: (texts[color], color))


def _combinations(manifest: TemplateManifest) -> list[Combination]:
    """Тройки «фон + текст + акцент», сложенные по слайдам.

    Сценарий сочетания словами не называется: это была бы интерпретация. Называются
    доля и номера слайдов, где оно встречено. Слайд, у макета которого нет фона,
    сочетания не даёт — читать текст было бы не по чему.
    """
    theme = manifest.theme
    seen: dict[tuple[str, str | None, str | None], list[int]] = defaultdict(list)
    for example in manifest.examples:
        background = _background_hex(manifest, example)
        if background is None:
            continue
        key = (
            background.upper(),
            _largest_text(example, theme),
            _noticeable_fill(example, theme, background),
        )
        seen[key].append(example.slide_index)

    total = sum(len(slides) for slides in seen.values())
    if total == 0:
        return []
    #: Порядок фиксирован: доля, затем сами цвета. Пустой цвет сортируется как пустая
    #: строка — сравнивать его с текстом напрямую нельзя.
    ordered = sorted(
        seen.items(),
        key=lambda item: (-len(item[1]), tuple(color or "" for color in item[0])),
    )
    return _collapse_combinations(
        [
            Combination(
                background_hex=background,
                text_hex=text,
                accent_hex=accent,
                share=round(len(slides) / total, SHARE_DIGITS),
                seen_on=sorted(slides),
                origin=Origin.MEASURED,
            )
            for (background, text, accent), slides in ordered
        ]
    )


def _collapse_combinations(combinations: list[Combination]) -> list[Combination]:
    """Свернуть хвост сочетаний в одну запись с суммарной долей — как у палитры.

    Сворачивается двоякое: то, что не поместилось в потолок, и тройка, у которой нет
    ни текста, ни акцента. Вторая — это один фон, а не сочетание: показывать в ней
    нечего, и она же делает запись хвоста узнаваемой. Отсутствие и текста, и акцента
    встречается только у неё, потому что всякая такая тройка сюда и уходит, — по этому
    признаку страница и отличает хвост от настоящего сочетания.
    """
    shown: list[Combination] = []
    collapsed: list[Combination] = []
    for combination in combinations:
        speaks = combination.text_hex is not None or combination.accent_hex is not None
        target = shown if speaks and len(shown) < COMBINATIONS_SHOWN else collapsed
        target.append(combination)

    if not collapsed:
        return shown
    return [
        *shown,
        Combination(
            #: Фон записи — фон самого крупного из свёрнутых: показать хвост нечем,
            #: кроме одной из его троек.
            background_hex=collapsed[0].background_hex,
            share=round(sum(item.share for item in collapsed), SHARE_DIGITS),
            seen_on=sorted(slide for item in collapsed for slide in item.seen_on),
            origin=Origin.MEASURED,
        ),
    ]


def _level(foreground_hex: str, background_hex: str) -> ContrastLevel:
    """Вердикт WCAG по паре. Формулы свои не заводим: они есть в `domain.rules`."""
    if meets_wcag_aa(foreground_hex, background_hex):
        return ContrastLevel.AA
    if meets_wcag_aa(foreground_hex, background_hex, large_text=True):
        return ContrastLevel.AA_LARGE
    return ContrastLevel.FAIL


def _label(theme: Theme, color_hex: str, fallback: str) -> str:
    """Имя слота темы, если цвет — это слот; иначе роль цвета словами."""
    for ref in ColorRef:
        if theme.colors.get(ref).upper() == color_hex.upper():
            return ref.value
    return fallback


def _pair(
    theme: Theme,
    foreground_hex: str,
    background_hex: str,
    *,
    foreground_label: str,
    background_label: str,
    from_theme: bool,
    approximate: bool = False,
) -> ContrastPair:
    level = _level(foreground_hex, background_hex)
    #: Порог пары — порог рабочего текста, запас — порог подписи: строкой таблицы
    #: пользуются и для абзаца, и для сноски, и «прошло впритык» обязано быть видно
    #: (change `a-minimum-is-not-a-norm`).
    verdict = readability(foreground_hex, background_hex, TextClass.BODY)
    return ContrastPair(
        foreground_hex=foreground_hex,
        background_hex=background_hex,
        foreground_label=_label(theme, foreground_hex, foreground_label),
        background_label=_label(theme, background_hex, background_label),
        ratio=round(contrast_ratio(foreground_hex, background_hex), RATIO_DIGITS),
        level=level,
        from_theme=from_theme,
        required=MIN_BODY,
        comfort=COMFORT_CAPTION,
        tight=verdict.passes and verdict.ratio < COMFORT_CAPTION,
        approximate=approximate,
        origin=Origin.MEASURED,
    )


def _theme_backgrounds(theme: Theme) -> tuple[str, str]:
    """Самый светлый и самый тёмный фоновые слоты темы — по ним и меряются акценты."""
    ordered = sorted(TEXT_SLOTS, key=lambda ref: relative_luminance(theme.colors.get(ref)))
    return theme.colors.get(ordered[-1]), theme.colors.get(ordered[0])


def _contrast_pairs(
    manifest: TemplateManifest, combinations: list[Combination]
) -> list[ContrastPair]:
    """Пары «текст на фоне»: объявленные темой и встреченные на примерах.

    Пара темы, не дотянувшая до AA, помечается риском: её обещал сам шаблон. Акцент,
    не дотянувший до AA, помечается иначе — он годен для графики и крупных меток, но
    не для абзаца, и прятать его незачем.
    """
    theme = manifest.theme
    light, dark = _theme_backgrounds(theme)
    pairs: dict[tuple[str, str, bool], ContrastPair] = {}

    def add(pair: ContrastPair) -> None:
        """Ключ включает происхождение: пара с примера не схлопывается с парой темы.

        Совпав по цветам, они говорят разное — тема обещает, примеры показывают, — и
        одна запись вместо двух оставила бы на странице только обещание.

        Отметки внутри одного происхождения складываются, а не достаются первой записи:
        акцент, чей цвет совпал со слотом схемы, приходит вторым и потерял бы отметку
        «только для графики» ровно из-за порядка.
        """
        key = (pair.foreground_hex.upper(), pair.background_hex.upper(), pair.from_theme)
        known = pairs.get(key)
        pairs[key] = (
            pair
            if known is None
            else known.model_copy(
                update={
                    "is_risk": known.is_risk or pair.is_risk,
                    "display_only": known.display_only or pair.display_only,
                }
            )
        )

    for foreground_ref, background_ref in SCHEME_PAIRS:
        pair = _pair(
            theme,
            theme.colors.get(foreground_ref),
            theme.colors.get(background_ref),
            foreground_label=foreground_ref.value,
            background_label=background_ref.value,
            from_theme=True,
        )
        add(pair.model_copy(update={"is_risk": pair.level is not ContrastLevel.AA}))

    for accent_ref in ACCENT_SLOTS:
        accent = theme.colors.get(accent_ref)
        for background in (light, dark):
            if accent.upper() == background.upper():
                continue
            pair = _pair(
                theme,
                accent,
                background,
                foreground_label=accent_ref.value,
                background_label="",
                from_theme=True,
            )
            add(pair.model_copy(update={"display_only": pair.level is not ContrastLevel.AA}))

    #: Фон, собранный из подложки во весь слайд, — усреднённый цвет картинки. Пара
    #: на нём считается, но честно помечается приблизительной: пункт 1 правил заказчика
    #: (прозрачность, градиент, изображение) манифестом не хранится.
    painted = {
        layout.background.color_hex.upper()
        for layout in manifest.layouts
        if layout.background is not None and layout.background.is_image
    }

    for combination in combinations:
        if combination.text_hex is None:
            continue
        add(
            _pair(
                theme,
                combination.text_hex,
                combination.background_hex,
                foreground_label="текст примеров",
                background_label="фон примеров",
                from_theme=False,
                approximate=combination.background_hex.upper() in painted,
            )
        )

    return list(pairs.values())


def _fonts_in_use(manifest: TemplateManifest) -> list[FontInUse]:
    """Гарнитуры по фактическому набору, от самой ходовой к редкой.

    Смысл раздела — расхождение: тема называет одну гарнитуру, а примеры набраны другой,
    и у всех трёх шаблонов кейса это так. Поэтому факт живёт отдельно от объявленного
    в `theme`, а не вместо него.

    Гарнитура, которой не набрано ни знака, в факты не попадает: тема перечисляет её
    наравне с остальными, но набран ею ровно ноль текста — это объявление, а не факт.
    """
    typeset = [usage for usage in manifest.usage.fonts if usage.chars > 0]
    return [
        FontInUse(
            family=usage.family,
            share=round(usage.share, SHARE_DIGITS),
            in_titles=usage.in_titles,
            in_body=usage.in_body,
            origin=Origin.MEASURED,
        )
        for usage in sorted(typeset, key=lambda usage: (-usage.share, usage.family))
    ]


def _number_sizes(manifest: TemplateManifest) -> NumberScale:
    """Три размера числа: крупный, средний, мелкий.

    Крупный — старший кегль, которым шаблон сам набрал показатель: KPI-компонент
    хранит кегли экземпляра по убыванию, и первый из них и есть число. Берётся максимум
    по всем KPI-компонентам, а не по самому частому: у шаблона кейса их два, и частый
    из них — мелкая строка списка, а число крупно набрано в другом.

    Средний и мелкий — ближайшие вниз по шкале шаблона (`next_size_down`, правило 6):
    своих кеглей мы не изобретаем. Показателей в шаблоне нет — мерить нечего, и тогда
    берутся три верхних кегля шкалы, а блок помечается достроенным.
    """
    kpi_sizes = [
        size
        for component in manifest.components
        if component.kind is ComponentKind.KPI
        for size in component.text_sizes_pt
        if size > 0
    ]
    if kpi_sizes:
        large = max(kpi_sizes)
        medium = next_size_down(manifest, large)
        small = next_size_down(manifest, medium) if medium is not None else None
        return NumberScale(large_pt=large, medium_pt=medium, small_pt=small, origin=Origin.MEASURED)

    #: Шкала короче трёх ступеней — недостающие размеры остаются пустыми: придумать
    #: кегль, которого в шаблоне нет, правило 6 не позволяет.
    top: list[float | None] = [*manifest.size_ladder_pt[:3], None, None, None]
    return NumberScale(large_pt=top[0], medium_pt=top[1], small_pt=top[2], origin=Origin.DERIVED)


def _components(manifest: TemplateManifest) -> list[ComponentCard]:
    """Каталог повторяющихся элементов шаблона — перенос разобранного парсером.

    Разбирать заново нечего: `parsing/components.py` уже нашёл повторы с равным шагом
    и снял с них пропорции. Здесь меняется только форма — доли округляются до того же
    знака, что и остальные доли страницы (G01), — и порядок.

    Порядок: вид, затем число слайдов, затем площадь экземпляра. Внутри вида первым
    идёт самый представительный — тот, что встречен на большем числе слайдов, — и
    странице не приходится выбирать его самой.
    """
    kinds = list(ComponentKind)
    ordered = sorted(
        manifest.components,
        key=lambda item: (
            kinds.index(item.kind),
            -len(item.seen_on),
            -item.width_share * item.height_share,
            item.seen_on,
        ),
    )
    return [
        ComponentCard(
            kind=item.kind,
            repeats=item.repeats,
            axis=item.axis,
            width_share=round(item.width_share, SHARE_DIGITS),
            height_share=round(item.height_share, SHARE_DIGITS),
            gap_share=round(item.gap_share, SHARE_DIGITS),
            text_sizes_pt=list(item.text_sizes_pt),
            fill_ref=item.fill_ref,
            fill_hex=item.fill_hex,
            seen_on=list(item.seen_on),
            origin=Origin.MEASURED,
        )
        for item in ordered
    ]


def measure(manifest: TemplateManifest, ds: DesignSystem) -> DesignSystem:
    """Дополнить структуру тем, что измеряется по слайдам-примерам."""
    combinations = _combinations(manifest)
    return ds.model_copy(
        update={
            "palette_roles": _palette_roles(manifest),
            "combinations": combinations,
            "contrast_pairs": _contrast_pairs(manifest, combinations),
            "fonts_in_use": _fonts_in_use(manifest),
            "number_sizes": _number_sizes(manifest),
            "components": _components(manifest),
        }
    )
