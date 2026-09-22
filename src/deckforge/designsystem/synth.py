"""Достроенное из примитивов шаблона: плашки, списки, элементы слайда, правила сборки.

Разделы дизайн-системы, которых в чужом шаблоне обычно нет вовсе. Страница обязана быть
полной: раздел не прячется оттого, что автор шаблона его не нарисовал, — вместо этого он
**достраивается из примитивов самого шаблона** и несёт признак `derived`.

Правило достройки одно и жёсткое: ни одного числа «из головы». Цвет — слот темы, кегль —
ступень `typography_scale`, отступ, радиус и толщина — доли базового шага сетки
(`ds.grid.spacing.base_emu`, посчитан в `derive`). Радиус 16 px был бы константой под
чужой шаблон и нарушением правила 2.

Две цветовые роли на три нужды. У плашки их три — заливка, текст на заливке, фон вокруг,
а полей в `SynthElement` два, и форма после таска 01 не меняется. Трактовка:

* `color_ref` — слот, которым окрашен **сам элемент**: заливка плашки, линия разделителя,
  полоса цитаты, знак или цифра у элемента без заливки;
* `on_color_ref` — слот **фона, на котором элемент лежит**, как и сказано в описании поля;
* цвет текста **на заливке** полем не хранится: он выводится по контрасту готовой
  `domain.rules.readable_text_ref(manifest, <цвет заливки>)` — тем же способом, что и
  везде в проекте, и потому не нуждается в хранении.
"""

from __future__ import annotations

from collections import Counter

from deckforge.designsystem.models import AssemblyRule, DesignSystem, SynthElement
from deckforge.domain.enums import ColorRef, TextRole
from deckforge.domain.rules import readable_text_ref
from deckforge.domain.template import LayoutSpec, TemplateManifest

#: Акцентные слоты темы по порядку. Из них берутся цвета тегов, бейджей и callout:
#: шаблон решает, какие они, мы решаем только порядок.
ACCENT_REFS: tuple[ColorRef, ...] = (
    ColorRef.ACCENT1,
    ColorRef.ACCENT2,
    ColorRef.ACCENT3,
    ColorRef.ACCENT4,
    ColorRef.ACCENT5,
    ColorRef.ACCENT6,
)

#: Разделы страницы, в которые собираются достроенные элементы.
GROUP_LABELS = "плашки"
GROUP_LISTS = "списки"
GROUP_ELEMENTS = "элементы"
GROUP_ACCESSIBILITY = "доступность"

#: Место роли в лестнице кеглей по убыванию — запасной путь для шаблона, у которого
#: роли в шкале нет. Не кегль, а номер ступени: сами кегли всегда шаблонные.
ROLE_RUNG: dict[TextRole, int] = {
    TextRole.TITLE: 0,
    TextRole.SUBTITLE: 1,
    TextRole.BODY: 2,
    TextRole.CAPTION: 3,
}

#: Во сколько базовых шагов сетки укладывается круглый бейдж каждого из трёх размеров.
BADGE_STEPS = (2, 3, 4)

#: Имена знаков иконочного списка из `assets/icons/lucide`. Здесь только имена: файлы
#: подставляет страница, а слой `designsystem` к диску не обращается (правило 1).
ICON_NAMES = ("target", "trending-up", "shield")

#: Толщина линии — доля базового шага: во столько раз тоньше шага каждый вид разделителя.
LINE_SHARE_THIN = 8
LINE_SHARE_ACCENT = 4
LINE_SHARE_BAR = 2

#: Радиус скругления — доля того же базового шага. Шестнадцать пикселей были бы
#: константой под чужой шаблон (правило 2).
RADIUS_SHARE_SOFT = 4
RADIUS_SHARE_PILL = 2

#: Откуда взялся базовый шаг — то же словами полей манифеста: правило сборки обязано
#: называть источник своего числа, иначе его нечем проверить.
STEP_SOURCE: dict[str, str] = {
    "gutter": "grid.gutter_emu",
    "margins_gcd": "grid.margins_emu",
    "margin": "grid.margins_emu",
    "columns": "grid.columns",
}


def _accents(manifest: TemplateManifest) -> list[ColorRef]:
    """Акценты темы без повторов: шаблон, у которого все шесть акцентов одного цвета,
    даёт один тег, а не шесть одинаковых."""
    colors = manifest.theme.colors
    unique: dict[str, ColorRef] = {}
    for ref in ACCENT_REFS:
        unique.setdefault(colors.get(ref).upper(), ref)
    return list(unique.values())


def _size(manifest: TemplateManifest, role: TextRole) -> float | None:
    """Кегль роли из шкалы шаблона; роли в шкале нет — соответствующая ступень лестницы."""
    step = manifest.typography(role)
    if step is not None:
        return step.size_pt
    ladder = manifest.size_ladder_pt
    if not ladder:
        return None
    return ladder[min(ROLE_RUNG[role], len(ladder) - 1)]


def _ascending(sizes: list[float | None]) -> list[float | None]:
    """Кегли по возрастанию: чем крупнее элемент, тем крупнее кегль."""
    known = sorted(size for size in sizes if size is not None)
    if len(known) != len(sizes):
        return [None] * len(sizes)
    return list(known)


def _page_background(ds: DesignSystem) -> ColorRef:
    """Слот фона страницы. Роль фона знает таск 02 по долям площади; ролей нет —
    светлый слот темы."""
    for role in ds.palette_roles:
        if role.role.value == "background" and role.nearest_ref is not None:
            return role.nearest_ref
    return ColorRef.LT1


def _labels(manifest: TemplateManifest, ds: DesignSystem) -> list[SynthElement]:
    """Раздел «Плашки и метки»: метка раздела, теги категорий, круглые бейджи."""
    accents = _accents(manifest)
    page = _page_background(ds)
    caption_pt = _size(manifest, TextRole.CAPTION)
    base = ds.grid.spacing.base_emu

    elements = [
        SynthElement(
            group=GROUP_LABELS,
            kind="section_label",
            title="Метка раздела",
            purpose="Название раздела над заголовком: мелким кеглем, акцентом, в верхнем регистре",
            text="РАЗДЕЛ",
            color_ref=accents[0],
            on_color_ref=page,
            size_pt=caption_pt,
            spacing_emu=base // 2,
        )
    ]
    elements += [
        SynthElement(
            group=GROUP_LABELS,
            kind="tag",
            title=f"Тег на слоте {ref.value}",
            purpose="Категория или статус: короткое слово заливкой акцента",
            text="Категория",
            color_ref=ref,
            on_color_ref=page,
            size_pt=caption_pt,
            spacing_emu=base // 2,
            radius_emu=base // 2,
        )
        for ref in accents
    ]
    badge_sizes = _ascending(
        [_size(manifest, role) for role in (TextRole.CAPTION, TextRole.BODY, TextRole.SUBTITLE)]
    )
    badge_titles = ("Малый бейдж", "Средний бейдж", "Крупный бейдж")
    elements += [
        SynthElement(
            group=GROUP_LABELS,
            kind="badge",
            title=title,
            purpose="Номер шага или пункта: цифра в круге поперечником в базовые шаги сетки",
            text=str(number),
            color_ref=accents[0],
            on_color_ref=page,
            size_pt=size_pt,
            spacing_emu=steps * base,
            radius_emu=steps * base // 2,
        )
        for number, (steps, title, size_pt) in enumerate(
            zip(BADGE_STEPS, badge_titles, badge_sizes, strict=True), start=1
        )
    ]
    return elements


def _lists(manifest: TemplateManifest, ds: DesignSystem) -> list[SynthElement]:
    """Раздел «Буллеты и списки»: три стиля, у каждого сказано, для чего он."""
    accents = _accents(manifest)
    page = _page_background(ds)
    body_pt = _size(manifest, TextRole.BODY)
    base = ds.grid.spacing.base_emu
    marker = ds.bullets

    bulleted = SynthElement(
        group=GROUP_LISTS,
        kind="bulleted",
        title="Маркированный список",
        purpose="Равноправные пункты: перечисление, в котором порядок ничего не значит",
        #: Шаблон, который маркера не задаёт, остаётся без маркера: дорисовать «типовую
        #: точку» значит придумать чужой дизайн (см. `BulletStyle`).
        text=marker.char or "",
        color_ref=marker.color_ref or accents[0],
        on_color_ref=page,
        size_pt=body_pt,
        spacing_emu=marker.margin_left_emu or base,
        origin=marker.origin,
    )
    numbered = SynthElement(
        group=GROUP_LISTS,
        kind="numbered",
        title="Нумерованный список",
        purpose="Шаги и порядок: когда важно, что сначала, а что потом",
        text="1",
        color_ref=accents[0],
        on_color_ref=page,
        size_pt=body_pt,
        spacing_emu=BADGE_STEPS[0] * base,
        radius_emu=BADGE_STEPS[0] * base // 2,
    )
    icons = [
        SynthElement(
            group=GROUP_LISTS,
            kind="icon",
            title=f"Иконочный пункт «{name}»",
            purpose="Аргументы со смыслом: знак подсказывает, о чём пункт, ещё до чтения",
            text=name,
            color_ref=accents[0],
            on_color_ref=page,
            size_pt=body_pt,
            spacing_emu=base,
        )
        for name in ICON_NAMES
    ]
    return [bulleted, numbered, *icons]


def _dominant(ds: DesignSystem) -> ColorRef:
    """Слот доминанты. Долю площади считает таск 02; ролей нет — первый акцент темы."""
    for role in ds.palette_roles:
        if role.role.value == "dominant" and role.nearest_ref is not None:
            return role.nearest_ref
    return ColorRef.ACCENT1


def _line(base_emu: int, share: int) -> int:
    """Толщина линии долей базового шага. Ноль линией не бывает — отсюда нижняя граница."""
    return max(1, base_emu // share)


def _pagination(manifest: TemplateManifest, ds: DesignSystem) -> list[SynthElement]:
    """Пагинация на трёх фонах: светлом, доминантном и тёмном. Цвет цифры — читаемый
    слот темы, посчитанный готовой `domain.rules`, а не подобранный на глаз."""
    colors = manifest.theme.colors
    backgrounds = (
        ("на светлом фоне", _page_background(ds)),
        ("на доминанте", _dominant(ds)),
        ("на тёмном фоне", ColorRef.DK1),
    )
    return [
        SynthElement(
            group=GROUP_ELEMENTS,
            kind="pagination",
            title=f"Пагинация {where}",
            purpose="Номер слайда: у нижнего поля, кеглем подписи, читаемым слотом темы",
            text="7",
            color_ref=readable_text_ref(manifest, colors.get(background)),
            on_color_ref=background,
            size_pt=_size(manifest, TextRole.CAPTION),
            spacing_emu=ds.grid.margins.bottom or ds.grid.spacing.base_emu,
        )
        for where, background in backgrounds
    ]


def _dividers(ds: DesignSystem) -> list[SynthElement]:
    """Четыре вида разделителей. Толщина каждого — доля базового шага сетки."""
    base = ds.grid.spacing.base_emu
    page = _page_background(ds)
    kinds = (
        (
            "divider_thin",
            "Тонкий разделитель",
            "Раздел внутри слайда: линия по цвету рамки, почти неслышная",
            ColorRef.LT2,
            LINE_SHARE_THIN,
        ),
        (
            "divider_accent",
            "Акцентный разделитель",
            "Смысловая граница: линия потолще, слотом акцента",
            _dominant(ds),
            LINE_SHARE_ACCENT,
        ),
        (
            "divider_dashed",
            "Пунктирный разделитель",
            "Необязательная граница: пунктир нейтральным слотом",
            ColorRef.DK2,
            LINE_SHARE_THIN,
        ),
        (
            "divider_quote_bar",
            "Вертикальная полоса",
            "Полоса слева от цитаты и выноски: та же линия, поставленная вертикально",
            _dominant(ds),
            LINE_SHARE_BAR,
        ),
    )
    return [
        SynthElement(
            group=GROUP_ELEMENTS,
            kind=kind,
            title=title,
            purpose=purpose,
            color_ref=color_ref,
            on_color_ref=page,
            spacing_emu=base,
            line_emu=_line(base, share),
        )
        for kind, title, purpose, color_ref, share in kinds
    ]


def _header_and_footer(manifest: TemplateManifest, ds: DesignSystem) -> list[SynthElement]:
    """Шапка и подвал — по `manifest.decor`. Логотипа или подвала в шаблоне нет — раздел
    всё равно строится и говорит об этом словами."""
    decor = manifest.decor
    logo, footer = decor.logo, decor.footer
    page = _page_background(ds)
    caption_pt = _size(manifest, TextRole.CAPTION)

    if logo is None:
        header_purpose = "Логотипа в шаблоне нет: шапку занимает только заголовок слайда"
        header_spacing = None
    else:
        side = "справа" if logo.x * 2 >= ds.grid.width_emu else "слева"
        header_purpose = f"Логотип шаблона стоит {side} в шапке, на постоянной высоте"
        header_spacing = logo.y

    return [
        SynthElement(
            group=GROUP_ELEMENTS,
            kind="header",
            title="Шапка слайда",
            purpose=header_purpose,
            color_ref=_dominant(ds) if logo is not None else None,
            on_color_ref=page,
            size_pt=caption_pt,
            spacing_emu=header_spacing,
        ),
        SynthElement(
            group=GROUP_ELEMENTS,
            kind="footer",
            title="Подвал слайда",
            purpose=(
                "Подвал шаблона: та же строка на каждом слайде, кеглем подписи"
                if footer.present
                else "Подвала в шаблоне нет: нижнее поле остаётся пустым"
            ),
            text="Название доклада",
            on_color_ref=page,
            size_pt=caption_pt,
            spacing_emu=footer.y_emu if footer.present else None,
        ),
    ]


def _accent(accents: list[ColorRef], index: int) -> ColorRef:
    """Акцент по порядку; акцентов меньше — берётся последний, а не выдумывается новый."""
    return accents[min(index, len(accents) - 1)]


def _table(manifest: TemplateManifest, ds: DesignSystem) -> list[SynthElement]:
    """Таблица: заголовок доминантой, чередование строк светлым слотом, дельты акцентами."""
    accents = _accents(manifest)
    page = _page_background(ds)
    base = ds.grid.spacing.base_emu
    body_pt = _size(manifest, TextRole.BODY)
    caption_pt = _size(manifest, TextRole.CAPTION)
    rows = (
        (
            "table_header",
            "Шапка таблицы",
            "Названия столбцов: заливка доминантой, текст читаемым слотом",
            "Показатель",
            _dominant(ds),
            body_pt,
        ),
        (
            "table_row_alt",
            "Чередование строк",
            "Каждая вторая строка подложена светлым слотом — глаз не теряет строку",
            "Строка таблицы",
            ColorRef.LT2,
            body_pt,
        ),
        (
            "table_delta_up",
            "Дельта роста",
            "Изменение вверх: знак и акцент, а не один только цвет",
            "+12 %",
            _accent(accents, 0),
            caption_pt,
        ),
        (
            "table_delta_down",
            "Дельта падения",
            "Изменение вниз: знак и другой акцент",
            "−4 %",
            _accent(accents, 1),
            caption_pt,
        ),
    )
    return [
        SynthElement(
            group=GROUP_ELEMENTS,
            kind=kind,
            title=title,
            purpose=purpose,
            text=text,
            color_ref=color_ref,
            on_color_ref=page,
            size_pt=size_pt,
            spacing_emu=base,
        )
        for kind, title, purpose, text, color_ref, size_pt in rows
    ]


def _quote_and_callouts(manifest: TemplateManifest, ds: DesignSystem) -> list[SynthElement]:
    """Цитата с вертикальной полосой и два callout — «ключевой инсайт» и «риск»."""
    accents = _accents(manifest)
    page = _page_background(ds)
    base = ds.grid.spacing.base_emu
    quote = SynthElement(
        group=GROUP_ELEMENTS,
        kind="quote",
        title="Цитата",
        purpose="Прямая речь: акцентная полоса слева, кегль подзаголовка",
        text="Прямая речь спикера в одну-две строки",
        color_ref=_dominant(ds),
        on_color_ref=page,
        size_pt=_size(manifest, TextRole.SUBTITLE),
        spacing_emu=base,
        line_emu=_line(base, LINE_SHARE_BAR),
    )
    callouts = (
        (
            "callout_insight",
            "Выноска «ключевой инсайт»",
            "Главная мысль слайда: её ищут глазами первой",
            "Ключевой инсайт",
            _accent(accents, 0),
        ),
        (
            "callout_risk",
            "Выноска «риск»",
            "Оговорка или риск: тот же блок на другом акценте",
            "Риск",
            _accent(accents, 1),
        ),
    )
    return [
        quote,
        *[
            SynthElement(
                group=GROUP_ELEMENTS,
                kind=kind,
                title=title,
                purpose=purpose,
                text=text,
                color_ref=color_ref,
                on_color_ref=page,
                size_pt=_size(manifest, TextRole.BODY),
                spacing_emu=base,
                radius_emu=base // RADIUS_SHARE_SOFT,
                line_emu=_line(base, LINE_SHARE_BAR),
            )
            for kind, title, purpose, text, color_ref in callouts
        ],
    ]


def _accessibility(ds: DesignSystem) -> list[SynthElement]:
    """Правило «смысл не только цветом». Правило, а не измерение, — отсюда `derived`."""
    return [
        SynthElement(
            group=GROUP_ACCESSIBILITY,
            kind="meaning_beyond_colour",
            title="Смысл не только цветом",
            purpose="Диаграмму и статус читают и те, кто не различает цвета",
            text=(
                "Рядом с цветом — подпись, узор или форма: цвет остаётся вторым "
                "носителем смысла, а не единственным"
            ),
            on_color_ref=_page_background(ds),
        )
    ]


def _slide_elements(manifest: TemplateManifest, ds: DesignSystem) -> list[SynthElement]:
    """Раздел «Базовые элементы слайда»."""
    return [
        *_dividers(ds),
        *_pagination(manifest, ds),
        *_header_and_footer(manifest, ds),
        *_table(manifest, ds),
        *_quote_and_callouts(manifest, ds),
    ]


def _body_layout(manifest: TemplateManifest) -> LayoutSpec | None:
    """Самый частый макет с телом. Тело — плейсхолдер основного текста, а не заголовка:
    вместимость заголовка про другое."""
    with_body = [
        layout
        for layout in manifest.layouts
        if any(
            place.ph_type == "BODY" or place.role is TextRole.BODY
            for place in layout.placeholders
        )
    ]
    if not with_body:
        return None
    kinds = Counter(layout.kind for layout in with_body)
    most_common = kinds.most_common(1)[0][0]
    return next(layout for layout in with_body if layout.kind is most_common)


def _assembly_rules(manifest: TemplateManifest, ds: DesignSystem) -> list[AssemblyRule]:
    """Правила сборки — из цифр шаблона. Правило без числа не пишем: это был бы чужой
    совет, выданный за анализ."""
    rules: list[AssemblyRule] = []
    sides = ds.grid.margins
    margins = [
        side for side in (sides.left, sides.right, sides.top, sides.bottom) if side > 0
    ]
    if margins:
        rules.append(
            AssemblyRule(
                text="Ближе наименьшего поля шаблона к краю слайда не ставится ничего",
                value=min(margins),
                unit="emu",
                source="grid.margins_emu",
            )
        )
    base = ds.grid.spacing.base_emu
    rules.append(
        AssemblyRule(
            text="Любой отступ — кратное базового шага сетки, промежуточных значений нет",
            value=base,
            unit="emu",
            source=STEP_SOURCE.get(ds.grid.spacing.base_source, "grid.margins_emu"),
        )
    )
    in_row = [item for item in manifest.components if item.axis == "row"]
    if in_row:
        widest = max(in_row, key=lambda item: len(item.seen_on))
        rules.append(
            AssemblyRule(
                text="Карточек в ряд — столько же, сколько ставил в ряд автор шаблона",
                value=widest.repeats,
                unit="шт",
                source="components.repeats",
            )
        )
    layout = _body_layout(manifest)
    if layout is not None and layout.capacity.max_bullets > 0:
        rules.append(
            AssemblyRule(
                text="Пунктов в теле слайда — не больше, чем вмещает самый частый макет",
                value=layout.capacity.max_bullets,
                unit="строк",
                source="layouts.capacity.max_bullets",
            )
        )
    return rules


def synthesize(manifest: TemplateManifest, ds: DesignSystem) -> DesignSystem:
    """Дополнить структуру тем, что достраивается из примитивов шаблона."""
    elements = [
        *_labels(manifest, ds),
        *_lists(manifest, ds),
        *_slide_elements(manifest, ds),
        *_accessibility(ds),
    ]
    return ds.model_copy(
        update={"synthesized": elements, "assembly_rules": _assembly_rules(manifest, ds)}
    )
