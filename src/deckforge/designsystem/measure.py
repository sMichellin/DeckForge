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

from deckforge.designsystem.models import (
    ColorRoleKind,
    Combination,
    ContrastLevel,
    ContrastPair,
    DesignSystem,
    Origin,
    PaletteRole,
)
from deckforge.domain.enums import ColorRef
from deckforge.domain.rules import (
    TEXT_SLOTS,
    contrast_ratio,
    delta_e_rgb,
    meets_wcag_aa,
    relative_luminance,
)
from deckforge.domain.template import (
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
    return [
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
) -> ContrastPair:
    level = _level(foreground_hex, background_hex)
    return ContrastPair(
        foreground_hex=foreground_hex,
        background_hex=background_hex,
        foreground_label=_label(theme, foreground_hex, foreground_label),
        background_label=_label(theme, background_hex, background_label),
        ratio=round(contrast_ratio(foreground_hex, background_hex), RATIO_DIGITS),
        level=level,
        from_theme=from_theme,
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
    pairs: dict[tuple[str, str], ContrastPair] = {}

    def add(pair: ContrastPair) -> None:
        pairs.setdefault((pair.foreground_hex.upper(), pair.background_hex.upper()), pair)

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
            )
        )

    return list(pairs.values())


def measure(manifest: TemplateManifest, ds: DesignSystem) -> DesignSystem:
    """Дополнить структуру тем, что измеряется по слайдам-примерам."""
    combinations = _combinations(manifest)
    return ds.model_copy(
        update={
            "palette_roles": _palette_roles(manifest),
            "combinations": combinations,
            "contrast_pairs": _contrast_pairs(manifest, combinations),
        }
    )
