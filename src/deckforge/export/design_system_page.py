"""Страница «Дизайн-система шаблона»: `DesignSystem` → одна самодостаточная html.

Change `design-system-page`, таск 04. Это единственный видимый результат прогона:
всё, что посчитали `derive`, `measure` и `synth`, человек видит только здесь.

Три свойства, ради которых модуль устроен именно так:

* **Самодостаточность.** Ни одной внешней ссылки: шрифты не встраиваются (их неоткуда
  взять), иконки Lucide вставляются содержимым, картинок нет вовсе. Файл открывается
  двойным кликом без интернета.
* **Ни одного литерального цвета вне `:root`.** Цвета собираются в `_Palette`, которая
  выдаёт разметке только `var(--…)`, а сами значения печатает одним блоком в начале
  стилей. Это тот же приём, что в `export/html.py`, и он же снимает правило 2: литерал
  приходит из темы шаблона, а не из кода.
* **Детерминированность** (G01). Ни времени генерации, ни случайных идентификаторов:
  два вызова на одной структуре дают побайтно равные строки.

Метка «измерено в шаблоне» / «достроено системой» нигде не проставляется руками: она
читается из признака `Origin` в данных. Иначе на первом же бедном шаблоне метка
разойдётся с правдой.
"""

from __future__ import annotations

from collections.abc import Iterable
from html import escape

from deckforge.designsystem.contrast import TextClass, readability, readable_from
from deckforge.designsystem.models import (
    AssemblyRule,
    ColorRoleKind,
    Combination,
    ComponentCard,
    ContrastLevel,
    ContrastPair,
    DesignSystem,
    Origin,
    PaletteRole,
    SynthElement,
    TypeLevel,
    TypeStep,
)
from deckforge.domain.enums import ColorRef
from deckforge.domain.rules import (
    TEXT_SLOTS,
    contrast_ratio,
    meets_wcag_aa,
    relative_luminance,
)
from deckforge.domain.units import emu_to_cm, emu_to_pt
from deckforge.rendering.icons import ICON_STROKE_WIDTH, ICON_VIEWBOX, icon_nodes

#: Доли, которыми цвет страницы подмешивается к цвету фона: поверхность карточки, линейка,
#: плашка, приглушённый текст. Это пропорции вёрстки — в EMU и слотах темы их нет, а брать
#: их из шаблона нечем: шаблон не знает, что у него будет страница документации.
_SURFACE_MIX, _LINE_MIX, _CHIP_MIX, _SOFT_MIX = 0.04, 0.16, 0.09, 0.45

#: Системные цвета браузера на случай темы без единого слота: страница не выдумывает цвет,
#: которого в шаблоне нет, а отдаёт покраску документу по умолчанию.
_SYSTEM_PAGE, _SYSTEM_INK = "Canvas", "CanvasText"

#: Русские названия ролей цвета и ступеней типографики. Заказчик не программист:
#: `background` и `body_large` на странице не появляются.
_ROLE_NAMES: dict[ColorRoleKind, str] = {
    ColorRoleKind.BACKGROUND: "фон",
    ColorRoleKind.DOMINANT: "доминанта",
    ColorRoleKind.ACCENT: "акцент",
    ColorRoleKind.RARE: "редкий",
    ColorRoleKind.TAIL: "свёрнутый хвост",
}
_LEVEL_NAMES: dict[TypeLevel, str] = {
    TypeLevel.DISPLAY: "Обложка",
    TypeLevel.SLIDE_TITLE: "Заголовок слайда",
    TypeLevel.SECTION_SUBTITLE: "Подзаголовок раздела",
    TypeLevel.CARD_TITLE: "Заголовок карточки",
    TypeLevel.BODY_LARGE: "Крупный текст",
    TypeLevel.BODY: "Основной текст",
    TypeLevel.CAPTION: "Подпись",
    TypeLevel.LABEL: "Метка",
}
_CONTRAST_NAMES: dict[ContrastLevel, str] = {
    ContrastLevel.AA: "AA",
    ContrastLevel.AA_LARGE: "AA для крупного",
    ContrastLevel.FAIL: "не проходит",
}
_COMPONENT_NAMES: dict[str, str] = {
    "tile": "Плитка",
    "picture_caption": "Картинка с подписью",
    "kpi": "Показатель",
}
_ORIGIN_NAMES: dict[Origin, str] = {
    Origin.MEASURED: "измерено в шаблоне",
    Origin.DERIVED: "достроено системой",
}
#: Виды, которые рисуют себя знаком или линией, а не заливкой. Только у них слот темы,
#: неразличимый на фоне, оставляет блок пустым: у заливки остаётся рамка и подпись,
#: и белая плашка на светлом фоне — это правда шаблона, а не поломка страницы.
_INK_KINDS = frozenset({"section_label", "bulleted", "icon", "pagination", "quote"})
_INK_PREFIXES = ("divider", "table_delta", "callout")


def _paints_with_ink(kind: str) -> bool:
    return kind in _INK_KINDS or kind.startswith(_INK_PREFIXES)


#: Образец русского текста для лестницы типографики: одна фраза на всех ступенях, чтобы
#: сравнивался кегль, а не длина строки.
_SAMPLE = "Съешь ещё этих мягких французских булок"


def render(ds: DesignSystem) -> str:
    """Собирает дизайн-систему шаблона в одну самодостаточную html-страницу."""
    return _Page(ds).document()


# --- цвета --------------------------------------------------------------------------


def _mix(a_hex: str, b_hex: str, share_of_a: float) -> str:
    """Смешивает два цвета по каналам: из них делаются поверхности и линейки страницы."""
    a, b = a_hex.lstrip("#"), b_hex.lstrip("#")
    channels = (
        round(int(a[i : i + 2], 16) * share_of_a + int(b[i : i + 2], 16) * (1 - share_of_a))
        for i in (0, 2, 4)
    )
    return "#" + "".join(f"{value:02X}" for value in channels)


class _Palette:
    """Единственное место страницы, где живут литеральные цвета.

    Разметка спрашивает имя переменной и никогда — значение, поэтому смена шаблона
    меняет ровно блок `:root`. Цвет, измеренный на примерах и не совпавший ни с одним
    слотом темы, получает порядковое имя: он приходит из данных, а не из кода.
    """

    def __init__(self, ds: DesignSystem) -> None:
        self._names: list[tuple[str, str]] = []
        self._by_hex: dict[str, str] = {}
        self._theme: dict[ColorRef, str] = {}
        for slot in ds.theme.slots:
            self._theme[slot.ref] = slot.color_hex
            self._names.append((slot.ref.value, slot.color_hex))
            self._by_hex.setdefault(slot.color_hex.upper(), slot.ref.value)
        if not self._theme:
            self._without_theme()
            return
        #: Слот, не объявленный темой, ссылается на ближайший объявленный: литерала для
        #: него взять неоткуда, а `var(--accent3)` в разметке уже мог появиться.
        fallback = self._theme.get(ColorRef.DK1) or next(iter(self._theme.values()))
        for ref in ColorRef:
            if ref not in self._theme:
                self._theme[ref] = fallback
                self._names.append((ref.value, fallback))

        page = max(TEXT_SLOTS, key=lambda ref: relative_luminance(self._theme[ref]))
        self.page_ref = page
        self.ink_ref = self.readable_on(self._theme[page])
        page_hex, ink_hex = self._theme[page], self._theme[self.ink_ref]
        self._add("ds-page", page_hex)
        self._add("ds-ink", ink_hex)
        self._add("ds-soft", _mix(ink_hex, page_hex, _SOFT_MIX))
        self._add("ds-line", _mix(ink_hex, page_hex, _LINE_MIX))
        self._add("ds-chip", _mix(ink_hex, page_hex, _CHIP_MIX))
        self._add("ds-surface", _mix(ink_hex, page_hex, _SURFACE_MIX))

    def _without_theme(self) -> None:
        """Тема без единого слота: красить нечем, и выдумывать цвет странице нельзя.

        Страница берёт системные цвета браузера — те самые, которыми он рисует любой
        документ без стилей. Разделы цвета при этом окажутся честно пустыми.
        """
        self.page_ref, self.ink_ref = ColorRef.LT1, ColorRef.DK1
        for ref in ColorRef:
            self._names.append((ref.value, _SYSTEM_INK))
        for name in ("ds-ink", "ds-soft", "ds-line", "ds-chip"):
            self._names.append((name, _SYSTEM_INK))
        for name in ("ds-page", "ds-surface"):
            self._names.append((name, _SYSTEM_PAGE))

    def _add(self, name: str, hex_color: str) -> None:
        self._names.append((name, hex_color))
        self._by_hex.setdefault(hex_color.upper(), name)

    def hex_of(self, ref: ColorRef) -> str:
        return self._theme.get(ref, "")

    def readable_on(self, background_hex: str, kind: TextClass = TextClass.BODY) -> ColorRef:
        """Слот темы, которым по этому фону можно писать текст этого класса.

        Берётся не «лучшее из имеющегося», а то, что действительно берёт порог:
        подписи нужно 7, рабочему тексту 4,5, крупному 3 (change `a-minimum-is-not-a-norm`).
        Порога не берёт ни один слот — тогда лучший, иначе страница нарисует пустое место;
        такие случаи слой называет отдельно, в разделе доступности.
        """
        if not background_hex or not self._theme:
            return self.ink_ref
        text_palette = {ref: self._theme[ref] for ref in TEXT_SLOTS if ref in self._theme}
        chosen = readable_from(text_palette, background_hex, kind)
        if chosen is not None:
            return chosen
        whole = readable_from(self._theme, background_hex, kind)
        if chosen is None and whole is not None:
            return whole
        return max(TEXT_SLOTS, key=lambda ref: contrast_ratio(self._theme[ref], background_hex))

    def var(self, name: str) -> str:
        return f"var(--{name})"

    def ref(self, ref: ColorRef | None) -> str:
        return self.var((ref or self.ink_ref).value)

    def literal(self, hex_color: str | None) -> str:
        """Имя переменной для измеренного цвета: сам литерал в разметку не попадает."""
        if hex_color is None:
            return self.var(self.ink_ref.value)
        key = hex_color.upper()
        if key not in self._by_hex:
            self._add(f"ds-c{len(self._names)}", key)
        return self.var(self._by_hex[key])

    def root_block(self) -> str:
        return "".join(f"  --{name}: {value};\n" for name, value in self._names)


# --- мелкие помощники ---------------------------------------------------------------


def _esc(text: str) -> str:
    return escape(text, quote=True)


def _pct(value: float, total: float) -> str:
    return f"{value / total * 100:.4f}%" if total else "0%"


def _share(value: float) -> str:
    """Доля в процентах словами для человека: 0,4 % там, где округление до целого врёт."""
    percent = value * 100
    text = f"{percent:.1f}" if percent < 10 else f"{percent:.0f}"
    return text.replace(".", ",") + " %"


def _num(value: float, digits: int = 2) -> str:
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return (text or "0").replace(".", ",")


def _cm(emu: int) -> str:
    return f"{_num(emu_to_cm(emu))} см"


def _slides(seen_on: Iterable[int]) -> str:
    numbers = list(seen_on)
    if not numbers:
        return "на примерах не встречено"
    head = ", ".join(str(n) for n in numbers[:6])
    return f"на слайдах {head}…" if len(numbers) > 6 else f"на слайдах {head}"


def _origin_tag(origin: Origin) -> str:
    """Метка блока. Берётся из признака в данных — руками нигде не проставляется."""
    return f'<span class="origin origin--{origin.value}">{_ORIGIN_NAMES[origin]}</span>'


def _sentence(text: str) -> str:
    """Фраза, законченная точкой: иначе назначение элемента и оговорка про контраст
    склеиваются в одну строку без границы между ними."""
    stripped = text.strip()
    if not stripped or stripped[-1] in ".!?:;":
        return stripped
    return f"{stripped}."


def _empty(reason: str) -> str:
    """Честно пустое место: шаблон не дал данных, и выдумывать их странице нечем."""
    return f'<p class="empty">{_esc(reason)}</p>'


class _Page:
    """Сборка документа. Порядок разделов — порядок образца заказчика, он зафиксирован."""

    def __init__(self, ds: DesignSystem) -> None:
        self.ds = ds
        self.p = _Palette(ds)

    # --- оболочка -------------------------------------------------------------------

    def document(self) -> str:
        body = "\n".join(
            (
                self.head(),
                self.section_colors(),
                self.section_accessibility(),
                self.section_typography(),
                self.section_labels(),
                self.section_lists(),
                self.section_elements(),
                self.section_grid(),
            )
        )
        return (
            '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>Дизайн-система — {_esc(self.ds.source_name)}</title>\n"
            f"<style>\n:root {{\n{self.p.root_block()}}}\n{self.css()}</style>\n</head>\n"
            f"<body>\n{body}\n</body>\n</html>\n"
        )

    def family(self, name: str) -> str:
        """Гарнитура шаблона с системным запасным вариантом: шрифты не встраиваются."""
        return f"'{_esc(name)}', system-ui, sans-serif" if name else "system-ui, sans-serif"

    def css(self) -> str:
        theme = self.ds.theme
        return f"""
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--ds-page); color: var(--ds-ink);
  font-family: {self.family(theme.minor_font)}; line-height: 1.5;
  -webkit-font-smoothing: antialiased; }}
.wrap {{ max-width: 68rem; margin: 0 auto; padding: 0 1.5rem; }}
.head {{ padding: 3rem 0 2rem; }}
.head h1 {{ font-family: {self.family(theme.major_font)}; font-size: clamp(1.7rem, 4vw, 2.6rem);
  margin: 0 0 .5rem; line-height: 1.15; }}
.head .lede {{ color: var(--ds-soft); margin: 0; max-width: 46rem; }}
.head .facts {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-top: 1.25rem; }}
section {{ padding: 2.5rem 0; border-top: 1px solid var(--ds-line); }}
section > .wrap > h2 {{ font-family: {self.family(theme.major_font)}; font-size: 1.35rem;
  margin: 0; letter-spacing: -.01em; }}
.lede {{ color: var(--ds-soft); margin: .5rem 0 1.5rem; max-width: 46rem; }}
h3 {{ font-size: .95rem; margin: 2rem 0 .75rem; font-weight: 600; }}
h3:first-of-type {{ margin-top: 0; }}
p {{ margin: 0 0 .75rem; }}
.origin {{ display: inline-block; font-size: .72rem; line-height: 1.6; padding: 0 .5rem;
  border-radius: 1rem; white-space: nowrap; vertical-align: middle;
  border: 1px solid var(--ds-line); color: var(--ds-soft); background: var(--ds-page); }}
.origin--measured {{ color: var(--ds-ink); border-color: var(--ds-ink); }}
.head-row {{ display: flex; align-items: baseline; gap: .75rem; flex-wrap: wrap; }}
.empty {{ color: var(--ds-soft); font-size: .9rem; padding: .75rem 1rem;
  border: 1px dashed var(--ds-line); border-radius: .5rem; }}
.grid {{ display: grid; gap: 1rem;
  grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr)); }}
.grid--wide {{ grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr)); }}
.card {{ border: 1px solid var(--ds-line); border-radius: .6rem; overflow: hidden;
  background: var(--ds-surface); }}
.card .body {{ padding: .75rem .9rem; font-size: .85rem; }}
.card .body b {{ display: block; font-size: .95rem; margin-bottom: .15rem; }}
.card .body span {{ display: block; color: var(--ds-soft); }}
.swatch {{ height: 4.5rem; border-bottom: 1px solid var(--ds-line); }}
.mono {{ font-family: ui-monospace, monospace; font-size: .8rem; letter-spacing: .02em; }}
.bar {{ display: flex; width: 100%; height: 2.5rem; border-radius: .4rem; overflow: hidden;
  border: 1px solid var(--ds-line); }}
.bar > i {{ display: block; }}
.bar-legend {{ display: flex; flex-wrap: wrap; gap: .25rem 1.25rem; margin-top: .6rem;
  font-size: .8rem; color: var(--ds-soft); }}
.bar-legend b {{ color: var(--ds-ink); font-weight: 600; }}
.bar-legend i {{ display: inline-block; width: .7rem; height: .7rem; border-radius: .2rem;
  border: 1px solid var(--ds-line); margin-right: .35rem; vertical-align: baseline; }}
.combo {{ border: 1px solid var(--ds-line); border-radius: .6rem; overflow: hidden; }}
.combo .demo {{ padding: 1rem; min-height: 6rem; }}
.combo .demo b {{ display: block; font-size: 1.05rem; }}
.combo .demo em {{ display: inline-block; font-style: normal; font-size: .75rem;
  padding: .1rem .5rem; border-radius: 1rem; margin-top: .6rem; }}
.combo .meta {{ padding: .6rem .9rem; font-size: .8rem; color: var(--ds-soft);
  background: var(--ds-surface); border-top: 1px solid var(--ds-line); }}
table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
th, td {{ text-align: left; padding: .5rem .6rem; border-bottom: 1px solid var(--ds-line);
  vertical-align: middle; }}
th {{ font-weight: 600; color: var(--ds-soft); font-size: .78rem; }}
td.num {{ text-align: right; font-family: ui-monospace, monospace; }}
.chip {{ display: inline-block; padding: .05rem .5rem; border-radius: 1rem; font-size: .75rem;
  border: 1px solid var(--ds-line); }}
.pairbox {{ display: inline-block; padding: .2rem .6rem; border-radius: .3rem;
  border: 1px solid var(--ds-line); white-space: nowrap; }}
.ladder {{ container-type: inline-size; border: 1px solid var(--ds-line);
  border-radius: .6rem; padding: 1rem 1.25rem; }}
.step {{ padding: .9rem 0; border-bottom: 1px solid var(--ds-line); }}
.step:last-child {{ border-bottom: 0; }}
.step .sample {{ display: block; line-height: 1.15; overflow-wrap: anywhere; }}
.step .meta {{ font-size: .78rem; color: var(--ds-soft); margin-top: .35rem;
  display: flex; gap: .4rem .9rem; flex-wrap: wrap; align-items: center; }}
.numbers {{ display: flex; gap: 2rem; align-items: baseline; flex-wrap: wrap;
  container-type: inline-size; border: 1px solid var(--ds-line); border-radius: .6rem;
  padding: 1.25rem; }}
.numbers div {{ text-align: center; }}
.numbers b {{ display: block; line-height: 1; font-variant-numeric: tabular-nums; }}
.numbers span {{ font-size: .78rem; color: var(--ds-soft); }}
.demos {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
.demo-cell {{ border: 1px solid var(--ds-line); border-radius: .6rem; padding: 1rem;
  min-width: 13rem; flex: 1 1 13rem; background: var(--ds-page); }}
.demo-cell .caption {{ font-size: .78rem; opacity: .72; margin-top: .6rem; }}
.demo-cell .caption b {{ display: block; font-weight: 600; opacity: 1; }}
.tag-demo {{ display: inline-block; padding: .15rem .7rem; }}
.badge-demo {{ display: inline-flex; align-items: center; justify-content: center;
  border-radius: 50%; font-variant-numeric: tabular-nums; }}
.list-demo {{ list-style: none; margin: 0; padding: 0; }}
.list-demo li {{ display: flex; gap: .6rem; align-items: flex-start; margin-bottom: .4rem; }}
.list-demo .marker {{ flex: none; display: inline-flex; align-items: center;
  justify-content: center; }}
.list-demo svg {{ width: 1.1em; height: 1.1em; }}
.rule {{ width: 100%; }}
.slide-map {{ position: relative; width: 100%; border: 1px solid var(--ds-line);
  border-radius: .3rem; background: var(--ds-page); overflow: hidden; }}
.slide-map .zone {{ position: absolute; }}
.slide-map .content {{ outline: 1px dashed var(--ds-line); }}
.slide-map .cols {{ position: absolute; inset: 0; display: flex; }}
.slide-map .cols > i {{ display: block; height: 100%; }}
.slide-map .cols > i:last-child {{ margin-right: 0 !important; }}
.slide-map .margin {{ background: var(--ds-chip); }}
.slide-map .content {{ display: flex; align-items: center; justify-content: center; }}
.slide-map .content span {{ position: relative; font-size: .75rem; color: var(--ds-soft); }}
.steps-scale {{ display: flex; flex-direction: column; gap: .35rem; }}
.steps-scale div {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .6rem;
  align-items: center; font-size: .78rem; color: var(--ds-soft); }}
.steps-scale i {{ display: block; height: .6rem; border-radius: .15rem; }}
ul.rules {{ margin: 0; padding-left: 1.1rem; }}
ul.rules li {{ margin-bottom: .5rem; }}
ul.rules span {{ color: var(--ds-soft); font-size: .8rem; }}
@media (max-width: 40rem) {{
  .numbers {{ gap: 1rem; }}
  table {{ display: block; overflow-x: auto; }}
  .mono {{ overflow-wrap: anywhere; }}
}}
"""

    def head(self) -> str:
        grid, theme = self.ds.grid, self.ds.theme
        facts = [
            ("Формат", f"{grid.aspect}, {_cm(grid.width_emu)} × {_cm(grid.height_emu)}"),
            ("Гарнитуры темы", f"{theme.major_font or '—'} / {theme.minor_font or '—'}"),
            ("Слотов темы", str(len(theme.slots))),
        ]
        chips = "".join(
            f'<span class="chip">{_esc(name)}: {_esc(value)}</span>' for name, value in facts
        )
        return (
            '<header class="head"><div class="wrap">'
            f"<h1>Дизайн-система шаблона</h1>"
            f'<p class="lede">Источник — {_esc(self.ds.source_name)}. '
            "Всё на этой странице либо измерено в самом шаблоне, либо достроено из его "
            "цветов, кеглей и шага сетки. У каждого блока стоит метка, которая из двух.</p>"
            f'<div class="facts">{chips}</div>'
            "</div></header>"
        )

    def section(self, title: str, lede: str, origin: Origin | None, inner: str) -> str:
        tag = _origin_tag(origin) if origin is not None else ""
        return (
            f'<section><div class="wrap">'
            f'<div class="head-row"><h2>{_esc(title)}</h2>{tag}</div>'
            f'<p class="lede">{_esc(lede)}</p>{inner}</div></section>'
        )

    # --- 02: семантика и сочетания --------------------------------------------------

    def section_colors(self) -> str:
        roles, combos = self.ds.palette_roles, self.ds.combinations
        origin = roles[0].origin if roles else Origin.DERIVED
        inner = "<h3>Роли и доли площади</h3>"
        if roles:
            inner += self.share_bar(roles) + self.role_cards(roles)
        else:
            inner += _empty(
                "В шаблоне нет слайдов-примеров: измерить доли площади не на чем. "
                "Цвета показаны только как слоты темы — в разделах ниже."
            )
        inner += "<h3>Сочетания, встреченные на примерах</h3>"
        inner += (
            self.combination_cards(combos)
            if combos
            else _empty("Сочетания собираются со слайдов-примеров, а их в шаблоне нет.")
        )
        return self.section(
            "02 — Семантика и сочетания",
            "Роль цвета выведена из доли площади слайдов-примеров, а не из того, сколько "
            "раз он встретился: подложка во весь слайд весит больше шести подписей.",
            origin,
            inner,
        )

    def share_bar(self, roles: list[PaletteRole]) -> str:
        total = sum(role.share for role in roles) or 1.0
        segments = "".join(
            f'<i style="width: {_pct(role.share, total)}; '
            f'background: {self.p.literal(role.color_hex)}"></i>'
            for role in roles
        )
        legend = "".join(
            f'<span><i style="background: {self.p.literal(role.color_hex)}"></i>'
            f"<b>{_esc(_ROLE_NAMES[role.role])}</b> {_esc(_share(role.share))}"
            f"{self.slot_suffix(role)}</span>"
            for role in roles
        )
        return f'<div class="bar">{segments}</div><div class="bar-legend">{legend}</div>'

    def slot_suffix(self, role: PaletteRole) -> str:
        return f" · {_esc(role.nearest_ref.value)}" if role.nearest_ref else ""

    def role_cards(self, roles: list[PaletteRole]) -> str:
        cards = []
        for role in roles:
            title = role.label or _ROLE_NAMES[role.role]
            slot = role.nearest_ref.value if role.nearest_ref else "нет близкого слота темы"
            cards.append(
                f'<div class="card"><div class="swatch" '
                f'style="background: {self.p.literal(role.color_hex)}"></div>'
                f'<div class="body"><b>{_esc(title)}</b>'
                f'<span class="mono">{_esc(role.color_hex)} · {_esc(slot)}</span>'
                f"<span>{_esc(_share(role.share))} площади, {_esc(_slides(role.seen_on))}</span>"
                f"</div></div>"
            )
        return f'<div class="grid">{"".join(cards)}</div>'

    def combination_cards(self, combos: list[Combination]) -> str:
        cards = [self.combination(combo, combo is combos[-1]) for combo in combos]
        return f'<div class="grid grid--wide">{"".join(cards)}</div>'

    def combination(self, combo: Combination, last: bool) -> str:
        #: Хвост опознаётся инвариантом таска 02: последняя запись без цвета текста
        #: и без акцента — это свёрнутые слайды, а не сочетание.
        tail = last and combo.text_hex is None and combo.accent_hex is None
        background = self.p.literal(combo.background_hex)
        #: Пара шаблона показывается как есть, пока она читается. Не читается — надпись
        #: рисуется слотом, который берёт порог, а под карточкой встаёт оговорка: иначе
        #: страница показывает пустой прямоугольник и сама нарушает правило, которое учит
        #: соблюдать (change `a-minimum-is-not-a-norm`).
        unreadable = ""
        text = self.p.ref(self.p.readable_on(combo.background_hex))
        if combo.text_hex:
            verdict = readability(combo.text_hex, combo.background_hex, TextClass.BODY)
            if verdict.passes:
                text = self.p.literal(combo.text_hex)
            else:
                unreadable = (
                    f"текст шаблона на этом фоне даёт {_num(verdict.ratio, 2)} "
                    f"при нужных {_num(verdict.required, 1)} — показан читаемым слотом"
                )
        accent = (
            f'<em style="background: {self.p.literal(combo.accent_hex)}; '
            f'color: {self.p.ref(self.p.readable_on(combo.accent_hex, TextClass.CAPTION))}">'
            "акцент</em>"
            if combo.accent_hex
            else ""
        )
        title = (
            f"Остальные слайды — ещё {len(combo.seen_on)}"
            if tail
            else f"{_esc(_share(combo.share))} слайдов-примеров"
        )
        note = (
            "Ни цвета текста, ни акцента: картинки и разделители."
            if tail
            else _slides(combo.seen_on)
        )
        return (
            f'<div class="combo"><div class="demo" '
            f'style="background: {background}; color: {text}">'
            f"<b>Заголовок на этом фоне</b>"
            f"<span>Основной текст, набранный тем же цветом.</span>{accent}</div>"
            f'<div class="meta">{_esc(title)} · {_esc(note)}'
            + (f" · {_esc(unreadable)}" if unreadable else "")
            + "</div></div>"
        )

    # --- 03: доступность ------------------------------------------------------------

    def section_accessibility(self) -> str:
        pairs = self.ds.contrast_pairs
        origin = pairs[0].origin if pairs else Origin.DERIVED
        theme_pairs = [pair for pair in pairs if pair.from_theme]
        seen_pairs = [pair for pair in pairs if not pair.from_theme]
        inner = "<h3>Пары слотов темы</h3>"
        inner += (
            self.contrast_table(theme_pairs)
            if theme_pairs
            else _empty("Пары темы не посчитаны: в шаблоне нет цветовой схемы.")
        )
        inner += "<h3>Пары, встреченные на примерах</h3>"
        inner += (
            self.contrast_table(seen_pairs)
            if seen_pairs
            else _empty("Слайдов-примеров в шаблоне нет — мерить пары не на чем.")
        )
        inner += self.contrast_defects()
        inner += self.accessibility_rules()
        return self.section(
            "03 — Доступность",
            "Коэффициент контраста посчитан по WCAG 2.1. Порог зависит от роли текста: "
            "крупный — 3, рабочий — 4,5, подпись — с запасом 7. «Риск» — это пара из самой "
            "темы шаблона, которая не проходит AA: шаблон противоречит сам себе, и прятать "
            "это нельзя.",
            origin,
            inner,
        )

    def contrast_defects(self) -> str:
        """Где шаблон не даёт читаемой пары ни одним слотом своей темы.

        Смысл раздела — увидеть это на разборе шаблона, а не на готовой презентации
        (change `a-minimum-is-not-a-norm`).
        """
        defects = self.ds.contrast_defects
        if not defects:
            return "<h3>Места без читаемой пары</h3>" + _empty(
                "Таких мест нет: для каждого элемента в теме нашёлся слот, берущий свой порог."
            )
        rows = "".join(
            f"<tr><td>{_esc(defect.where)}</td><td>{_esc(defect.text_class)}</td>"
            f'<td class="mono">{_esc(defect.background_label or defect.background_hex)}</td>'
            f'<td class="num">{_esc(_num(defect.required, 1))}</td>'
            f'<td class="num">{_esc(_num(defect.best_ratio, 2))}</td>'
            f'<td class="mono">{_esc(defect.best_ref.value if defect.best_ref else "—")}</td>'
            "</tr>"
            for defect in defects
        )
        return (
            "<h3>Места без читаемой пары</h3>"
            "<table><thead><tr><th>Где</th><th>Класс текста</th><th>Фон</th>"
            '<th class="num">Нужно</th><th class="num">Лучшее в теме</th>'
            "<th>Слот</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    def contrast_table(self, pairs: list[ContrastPair]) -> str:
        rows = "".join(self.contrast_row(pair) for pair in pairs)
        return (
            "<table><thead><tr><th>Пара</th><th>Текст на фоне</th>"
            '<th class="num">Контраст</th><th class="num">Нужно</th>'
            "<th>Оценка</th><th>Примечание</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )

    def contrast_row(self, pair: ContrastPair) -> str:
        notes = []
        if pair.is_risk:
            notes.append("риск: пара темы не проходит AA")
        if pair.display_only:
            notes.append("только для графики и крупных меток")
        if pair.tight:
            notes.append(
                f"впритык: минимум взят, до запаса {_num(pair.comfort, 1)} не хватает — "
                "для подписи и сноски не брать"
            )
        if pair.approximate:
            notes.append("фон подложкой: цвет усреднён, оценка приблизительна")
        sample = (
            f'<span class="pairbox" style="background: {self.p.literal(pair.background_hex)}; '
            f'color: {self.p.literal(pair.foreground_hex)}">Пример текста</span>'
        )
        return (
            f'<tr><td class="mono">{_esc(pair.foreground_label or pair.foreground_hex)} → '
            f"{_esc(pair.background_label or pair.background_hex)}</td>"
            f"<td>{sample}</td>"
            f'<td class="num">{_esc(_num(pair.ratio, 2))}</td>'
            f'<td class="num">{_esc(_num(pair.required, 1))}</td>'
            f'<td><span class="chip">{_esc(_CONTRAST_NAMES[pair.level])}</span></td>'
            f"<td>{_esc('; '.join(notes) or '—')}</td></tr>"
        )

    def accessibility_rules(self) -> str:
        rules = self.group("доступность")
        if not rules:
            return ""
        cells = "".join(
            f'<div class="demo-cell"><b>{_esc(rule.title)}</b>'
            f"<p>{_esc(rule.text)}</p>"
            f'<div class="caption">{_esc(rule.purpose)} {_origin_tag(rule.origin)}</div>'
            "</div>"
            for rule in rules
        )
        return f'<h3>Правила</h3><div class="demos">{cells}</div>'

    # --- 04: типографика ------------------------------------------------------------

    def section_typography(self) -> str:
        steps = self.ds.typography.steps
        inner = "<h3>Лестница ролей</h3>"
        inner += (
            f'<div class="ladder">{"".join(self.type_step(step) for step in steps)}</div>'
            if steps
            else _empty("Типографической шкалы в шаблоне нет.")
        )
        inner += self.fonts_block()
        inner += self.numbers_block()
        return self.section(
            "04 — Типографика",
            "Образцы набраны в пропорции шаблона: кегль задан долей от ширины блока, "
            "а доля — это отношение кегля к ширине слайда. Лестница выглядит так же, "
            "как на слайде, при любой ширине окна.",
            self.ds.typography.origin,
            inner,
        )

    def type_step(self, step: TypeStep) -> str:
        weight = "700" if step.bold else "400"
        style = "italic" if step.italic else "normal"
        spacing = f"{_num(step.line_spacing)}" if step.line_spacing else "по умолчанию"
        meta = " · ".join(
            (
                f"{_num(step.size_pt, 1)} pt",
                step.font_family,
                "жирный" if step.bold else "обычный",
                f"интерлиньяж {spacing}",
                f"цвет {step.color_ref.value}",
            )
        )
        return (
            f'<div class="step"><span class="sample" style="'
            f"font-size: {step.width_share * 100:.4f}cqw; font-family: "
            f"{self.family(step.font_family)}; font-weight: {weight}; font-style: {style}; "
            f'color: {self.p.ref(step.color_ref)}">{_esc(_SAMPLE)}</span>'
            f'<div class="meta"><b>{_esc(_LEVEL_NAMES[step.level])}</b>'
            f'<span>{_esc(step.purpose)}</span><span class="mono">{_esc(meta)}</span>'
            f"{_origin_tag(step.origin)}</div></div>"
        )

    def fonts_block(self) -> str:
        fonts = self.ds.fonts_in_use
        theme = self.ds.theme
        declared = (
            f"<p>Тема объявляет <b>{_esc(theme.major_font or '—')}</b> для заголовков и "
            f"<b>{_esc(theme.minor_font or '—')}</b> для текста.</p>"
        )
        if not fonts:
            return (
                "<h3>Чем шаблон набран на самом деле</h3>"
                + declared
                + _empty("Слайдов-примеров нет: фактический набор измерить не на чем.")
            )
        rows = "".join(
            f'<tr><td style="font-family: {self.family(font.family)}">{_esc(font.family)}</td>'
            f'<td class="num">{_esc(_share(font.share))}</td>'
            f"<td>{_esc('в заголовках' if font.in_titles else '')}"
            f"{_esc(', в тексте' if font.in_body else '')}</td>"
            f"<td>{_origin_tag(font.origin)}</td></tr>"
            for font in fonts
        )
        return (
            "<h3>Чем шаблон набран на самом деле</h3>"
            + declared
            + '<table><thead><tr><th>Гарнитура</th><th class="num">Доля знаков</th>'
            f"<th>Где встречена</th><th></th></tr></thead><tbody>{rows}</tbody></table>"
        )

    def numbers_block(self) -> str:
        scale = self.ds.number_sizes
        sizes = [
            (scale.large_pt, "крупное число"),
            (scale.medium_pt, "среднее"),
            (scale.small_pt, "мелкое"),
        ]
        width = self.ds.grid.width_emu
        cells = []
        for size_pt, name in sizes:
            if size_pt is None:
                cells.append(f"<div><b>—</b><span>{_esc(name)}: в шаблоне нет</span></div>")
                continue
            share = size_pt * 100 / emu_to_pt(width)
            cells.append(
                f'<div><b style="font-size: {share:.4f}cqw">128</b>'
                f"<span>{_esc(name)}, {_esc(_num(size_pt, 1))} pt</span></div>"
            )
        return (
            f"<h3>Шкала для чисел {_origin_tag(scale.origin)}</h3>"
            f'<div class="numbers">{"".join(cells)}</div>'
        )

    # --- 05, 06, 07: достроенные элементы -------------------------------------------

    def group(self, name: str) -> list[SynthElement]:
        return [item for item in self.ds.synthesized if item.group == name]

    def section_labels(self) -> str:
        items = self.group("плашки")
        inner = (
            self.demo_cells(items)
            if items
            else _empty("Плашки достраиваются из акцентов темы — их в шаблоне не нашлось.")
        )
        return self.section(
            "05 — Плашки и метки",
            "Ничего из этого в шаблоне не нарисовано: плашки собраны из его акцентов, "
            "кеглей и базового шага сетки. Цвет текста на заливке выбран замером контраста.",
            items[0].origin if items else Origin.DERIVED,
            inner,
        )

    def section_lists(self) -> str:
        items = self.group("списки")
        bullets = self.ds.bullets
        marker = bullets.char or "знак не задан"
        inner = f'<p>Маркер первого уровня шаблона: <b class="mono">{_esc(marker)}</b>, '
        inner += (
            f"отступ списка {_esc(_cm(bullets.margin_left_emu))}, "
            f"выступ маркера {_esc(_cm(-bullets.indent_emu))}. {_origin_tag(bullets.origin)}</p>"
        )
        inner += (
            self.demo_cells(items)
            if items
            else _empty("Списков достроить не удалось: в шаблоне нет ни маркера, ни шкалы кеглей.")
        )
        return self.section(
            "06 — Буллеты и списки",
            "Три стиля и подпись, когда какой брать: маркированный — знаком самого шаблона, "
            "нумерованный и иконочный — достроены.",
            items[0].origin if items else Origin.DERIVED,
            inner,
        )

    def section_elements(self) -> str:
        items = self.group("элементы")
        inner = "<h3>Повторяющиеся элементы шаблона</h3>"
        inner += (
            self.component_cards()
            if self.ds.components
            else _empty("Повторяющихся элементов на слайдах-примерах не нашлось.")
        )
        inner += "<h3>Достроенные элементы</h3>"
        inner += (
            self.demo_cells(items)
            if items
            else _empty(
                "Элементы достраиваются из цвета, кегля и шага шаблона — данных не хватило."
            )
        )
        return self.section(
            "07 — Базовые элементы слайда",
            "Сверху — то, что автор шаблона нарисовал сам и повторил на нескольких слайдах. "
            "Ниже — элементы, которых в шаблоне нет, собранные из его же примитивов.",
            self.ds.components[0].origin if self.ds.components else Origin.DERIVED,
            inner,
        )

    def component_cards(self) -> str:
        return f'<div class="grid grid--wide">{
            "".join(self.component_card(card) for card in self.ds.components)
        }</div>'

    def component_card(self, card: ComponentCard) -> str:
        name = _COMPONENT_NAMES.get(card.kind.value, card.kind.value)
        axis = "в ряд" if card.axis == "row" else "в столбец"
        fill = (
            self.p.ref(card.fill_ref)
            if card.fill_ref
            else (self.p.literal(card.fill_hex) if card.fill_hex else self.p.var("ds-chip"))
        )
        sizes = ", ".join(f"{_num(size, 1)} pt" for size in card.text_sizes_pt) or "нет текста"
        #: Имя элемента стоит под образцом, а не по его заливке: на заливке шаблона
        #: подписи может не хватить контраста, а менять заливку нельзя — она измерена
        #: (change `a-minimum-is-not-a-norm`).
        preview = f'<div class="swatch" style="background: {fill}"></div>'
        return (
            f'<div class="card">{preview}<div class="body">'
            f"<b>{_esc(name)} × {card.repeats} {_esc(axis)}</b>"
            f"<span>ширина {_esc(_share(card.width_share))} слайда, высота "
            f"{_esc(_share(card.height_share))}, шаг {_esc(_share(card.gap_share))}</span>"
            f"<span>кегли: {_esc(sizes)}</span>"
            f"<span>{_esc(_slides(card.seen_on))}</span>"
            f"</div></div>"
        )

    def card_text_ref(self, card: ComponentCard) -> ColorRef:
        """Цвет надписи на заливке карточки — замером, а не на глаз."""
        if card.fill_ref is not None:
            return self.p.readable_on(self.p.hex_of(card.fill_ref), TextClass.CAPTION)
        if card.fill_hex is not None:
            return self.p.readable_on(card.fill_hex, TextClass.CAPTION)
        return self.p.ink_ref

    # --- демонстрации достроенных элементов -----------------------------------------

    def demo_cells(self, items: list[SynthElement]) -> str:
        return f'<div class="demos">{"".join(self.demo_cell(item) for item in items)}</div>'

    def demo_cell(self, item: SynthElement) -> str:
        background = self.p.ref(item.on_color_ref)
        ink, fallback = self.visible_ink(item)
        note = self.layer_note(item) or fallback
        return (
            f'<div class="demo-cell" style="background: {background}; '
            f'color: {self.p.ref(self.on_background(item))}">'
            f"{self.demo(item, ink)}"
            f'<div class="caption"><b>{_esc(item.title)}</b>{_esc(_sentence(item.purpose))} '
            f"{_esc(_sentence(note))} {self.demo_numbers(item)} {_origin_tag(item.origin)}"
            "</div></div>"
        )

    def layer_note(self, item: SynthElement) -> str:
        """Оговорку про подменённый знак пишет слой — рендер её только показывает."""
        return item.note

    def visible_ink(self, item: SynthElement) -> tuple[str, str]:
        """Цвет знака или линии элемента и оговорка, если этим слотом на этом фоне не видно.

        Порог тот же, что у домена для графики и крупного текста. Ниже него знак исчезает,
        и блок выглядит пустым вместо того, чтобы что-то показать: заливку так подменять
        нельзя (белая плашка на светлом фоне — это правда шаблона), а знак — нужно.
        """
        ref, on = item.shown_ref or item.color_ref, item.on_color_ref
        fore, back = self.p.hex_of(ref) if ref else "", self.p.hex_of(on) if on else ""
        if not _paints_with_ink(item.kind):
            return self.p.ref(ref), ""
        if not fore or not back or meets_wcag_aa(fore, back, large_text=True):
            return self.p.ref(ref), ""
        ratio = _num(contrast_ratio(fore, back), 2)
        assert ref is not None
        return (
            self.p.ref(self.p.readable_on(back)),
            f"Слот {ref.value} на этом фоне неразличим — контраст {ratio}; "
            "знак показан читаемым слотом темы.",
        )

    def on_background(self, item: SynthElement) -> ColorRef:
        base = item.on_color_ref
        return self.p.readable_on(self.p.hex_of(base)) if base else self.p.ink_ref

    def demo_numbers(self, item: SynthElement) -> str:
        parts = []
        if item.size_pt is not None:
            parts.append(f"{_num(item.size_pt, 1)} pt")
        if item.spacing_emu:
            parts.append(f"отступ {_cm(item.spacing_emu)}")
        if item.radius_emu:
            parts.append(f"радиус {_cm(item.radius_emu)}")
        if item.line_emu:
            parts.append(f"линия {_cm(item.line_emu)}")
        return f'<span class="mono">{_esc(" · ".join(parts))}</span>' if parts else ""

    def font_size(self, size_pt: float | None) -> str:
        """Кегль образца в долях ширины слайда — та же пропорция, что на слайде."""
        if size_pt is None:
            return "1rem"
        share = size_pt * 100 / emu_to_pt(self.ds.grid.width_emu)
        return f"{share:.4f}cqw"

    def demo(self, item: SynthElement, ink: str) -> str:
        #: Заливка и надпись — те, что выбрал слой: он знает правило, рендер только рисует.
        kind = item.kind
        fill = self.p.ref(item.plate_ref or item.color_ref)
        #: Надпись на плашке — подпись, а не абзац: порог у неё свой, с запасом.
        #: Без этого цифра бейджа и слово тега получали цвет «по остаточному принципу»
        #: (change `a-minimum-is-not-a-norm`).
        plate = item.plate_ref or item.color_ref
        on_fill = self.p.ref(
            item.shown_ref
            if item.shown_ref is not None
            else (self.p.readable_on(self.p.hex_of(plate), TextClass.CAPTION) if plate else None)
        )
        text = _esc(item.text)
        if kind == "section_label":
            return (
                f'<span style="color: {ink}; letter-spacing: .12em; font-weight: 600; '
                f'font-size: .8rem">{text.upper()}</span>'
            )
        if kind == "tag":
            radius = self.rem(item.radius_emu)
            #: Акцент без запаса под подпись остаётся границей: заливка с надписью
            #: на минимуме читается плохо при любой палитре (change `a-minimum-is-not-a-norm`).
            paint = (
                f"background: transparent; color: {fill}; box-shadow: inset 0 0 0 2px {fill}"
                if item.outlined
                else f"background: {fill}; color: {on_fill}"
            )
            return (
                f'<span class="tag-demo" style="{paint}; '
                f'border-radius: {radius}; font-size: .85rem">{text}</span>'
            )
        if kind == "badge":
            size = self.rem(item.spacing_emu)
            paint = (
                f"background: transparent; color: {fill}; box-shadow: inset 0 0 0 2px {fill}"
                if item.outlined
                else f"background: {fill}; color: {on_fill}"
            )
            return (
                f'<span class="badge-demo" style="{paint}; '
                f'width: {size}; height: {size}; font-size: .85rem">{text}</span>'
            )
        if kind in {"bulleted", "numbered", "icon"}:
            return self.list_demo(item, ink)
        if kind.startswith("divider"):
            return self.divider(item, ink)
        if kind == "pagination":
            return f'<span style="color: {ink}; font-size: .85rem">{text} / 24</span>'
        if kind in {"header", "footer"}:
            return f'<span style="font-size: .85rem; opacity: .75">{text or "—"}</span>'
        if kind == "table_header":
            return self.table_demo(item)
        if kind == "table_row_alt":
            return self.table_demo(item, alternate=True)
        if kind.startswith("table_delta"):
            sign = "▲" if kind.endswith("up") else "▼"
            return f'<span style="color: {ink}; font-weight: 600">{sign} {text}</span>'
        if kind == "quote":
            return self.quote_demo(item, ink)
        if kind.startswith("callout"):
            return self.callout_demo(item, ink)
        return f"<span>{text}</span>" if text else ""

    def rem(self, emu: int | None) -> str:
        """Размер достроенного элемента в долях базового шага сетки, переведённых в rem."""
        base = self.ds.grid.spacing.base_emu
        return f"{(emu or 0) / base:.3f}rem" if base else "0"

    def list_demo(self, item: SynthElement, ink: str) -> str:
        markers = {
            "bulleted": lambda: f'<span style="color: {ink}">{_esc(item.text)}</span>',
            "numbered": lambda: self.numbered_marker(item),
            "icon": lambda: self.icon(item, ink),
        }
        marker = markers[item.kind]()
        rows = "".join(
            f'<li><span class="marker">{marker}</span>'
            f"<span>Пункт списка, одна строка смысла</span></li>"
            for _ in range(3)
        )
        return f'<ul class="list-demo">{rows}</ul>'

    def numbered_marker(self, item: SynthElement) -> str:
        fill = self.p.ref(item.color_ref)
        on_fill = self.p.ref(
            self.p.readable_on(self.p.hex_of(item.color_ref)) if item.color_ref else None
        )
        size = self.rem(item.spacing_emu)
        return (
            f'<span class="badge-demo" style="background: {fill}; color: {on_fill}; '
            f'width: {size}; height: {size}; font-size: .7rem">1</span>'
        )

    def icon(self, item: SynthElement, ink: str) -> str:
        """Иконка Lucide вставляется содержимым: файл рядом со страницей не лежит."""
        nodes = "".join(
            f"<{tag} " + " ".join(f'{key}="{_esc(value)}"' for key, value in attrs.items()) + "/>"
            for tag, attrs in icon_nodes(item.text) or []
        )
        if not nodes:
            return '<span aria-hidden="true">•</span>'
        return (
            f'<svg viewBox="0 0 {ICON_VIEWBOX} {ICON_VIEWBOX}" fill="none" '
            f'stroke="currentColor" stroke-width="{ICON_STROKE_WIDTH}" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true" '
            f'style="color: {ink}">{nodes}</svg>'
        )

    def divider(self, item: SynthElement, ink: str) -> str:
        color = ink
        thickness = self.rem(item.line_emu)
        if item.kind == "divider_dashed":
            return (
                f'<div class="rule" style="border-top: {thickness} dashed {color}; '
                f'min-height: {thickness}"></div>'
            )
        if item.kind == "divider_quote_bar":
            return (
                f'<div style="border-left: {thickness} solid {color}; padding-left: .75rem; '
                'min-height: 2.5rem"><span style="font-size: .85rem">Вертикальная полоса '
                "слева от блока</span></div>"
            )
        return (
            f'<div class="rule" style="background: {color}; height: {thickness}; '
            'min-height: 1px"></div>'
        )

    def table_demo(self, item: SynthElement, *, alternate: bool = False) -> str:
        """Демонстрация таблицы: цвет текста считается на той заливке, на которой он лежит.

        Цвет ставится каждой ячейке, а не строке: общий стиль страницы красит `th`
        приглушённым цветом документа, и на заливке шаблона тот оказался бы невидим.
        """
        filled = f"background: {self.p.ref(item.color_ref)}; color: {self.on_fill(item)}"
        plain = f"color: {self.p.ref(self.on_background(item))}"
        head_style = plain if alternate else filled
        head = (
            f'<tr><th style="{head_style}">{_esc(item.text)}</th>'
            f'<th style="{head_style}">Значение</th></tr>'
        )
        rows = "".join(
            f'<tr><td style="{filled if alternate and index % 2 else plain}">'
            f"{_esc(item.text)} {index + 1}</td>"
            f'<td class="num" style="{filled if alternate and index % 2 else plain}">'
            f"{(index + 1) * 12}</td></tr>"
            for index in range(3)
        )
        return f"<table>{head}{rows}</table>"

    def on_fill(self, item: SynthElement) -> str:
        """Цвет текста на заливке элемента — замером контраста, а не на глаз."""
        base = self.p.hex_of(item.color_ref) if item.color_ref else ""
        return self.p.ref(self.p.readable_on(base) if base else None)

    def quote_demo(self, item: SynthElement, ink: str) -> str:
        return (
            f'<div style="border-left: {self.rem(item.line_emu)} solid '
            f"{ink}; padding-left: .9rem; "
            f'font-size: 1.05rem">{_esc(item.text)}</div>'
        )

    def callout_demo(self, item: SynthElement, ink: str) -> str:
        color = ink
        return (
            f'<div style="border-left: {self.rem(item.line_emu)} solid {color}; '
            f'border-radius: {self.rem(item.radius_emu)}; padding: .6rem .9rem">'
            f'<b style="color: {color}">{_esc(item.text)}</b>'
            "<div>Одна фраза, которую читают первой.</div></div>"
        )

    # --- 08: сетка и модуль слайда ---------------------------------------------------

    def section_grid(self) -> str:
        grid = self.ds.grid
        inner = "<h3>Цифры сетки</h3>" + self.grid_facts()
        inner += f"<h3>Шкала отступов {_origin_tag(grid.spacing.origin)}</h3>"
        inner += self.spacing_scale()
        inner += f"<h3>Анатомия слайда {_origin_tag(grid.guides_origin)}</h3>"
        inner += self.anatomy()
        inner += "<h3>Правила сборки</h3>"
        inner += (
            self.rules()
            if self.ds.assembly_rules
            else _empty("Правило без числа из шаблона на страницу не попадает — чисел не нашлось.")
        )
        return self.section(
            "08 — Сетка и модуль слайда",
            "Схема ниже нарисована стилями по цифрам шаблона: макеты не рендерились. "
            "Все размеры — проценты от сторон слайда.",
            grid.origin,
            inner,
        )

    def grid_facts(self) -> str:
        grid = self.ds.grid
        margins = grid.margins
        facts = [
            ("Формат", f"{grid.aspect}"),
            ("Размер слайда", f"{_cm(grid.width_emu)} × {_cm(grid.height_emu)}"),
            (
                "Поля",
                f"слева {_cm(margins.left)}, справа {_cm(margins.right)}, "
                f"сверху {_cm(margins.top)}, снизу {_cm(margins.bottom)}",
            ),
            ("Колонок", f"{grid.columns} по {_cm(grid.column_width_emu)}"),
            ("Межколонник", _cm(grid.gutter_emu)),
            (
                "Зона контента",
                f"{_cm(grid.content_width_emu)} × {_cm(grid.content_height_emu)}",
            ),
            (
                "Базовый шаг",
                f"{_cm(grid.spacing.base_emu)} (источник: {grid.spacing.base_source}), "
                f"в наименьшем поле — {grid.spacing.steps_in_margin}",
            ),
        ]
        rows = "".join(
            f"<tr><th>{_esc(name)}</th><td>{_esc(value)}</td></tr>" for name, value in facts
        )
        return f"<table><tbody>{rows}</tbody></table>"

    def spacing_scale(self) -> str:
        spacing = self.ds.grid.spacing
        if not spacing.steps_emu:
            return _empty("Кратностей базового шага в шаблоне не нашлось.")
        widest = max(spacing.steps_emu)
        bars = "".join(
            f'<div><b><i style="width: {_pct(step, widest)}; '
            f'background: {self.p.ref(ColorRef.ACCENT1)}"></i></b>'
            f"<span>×{_num(step / spacing.base_emu, 1)} — {_esc(_cm(step))}</span></div>"
            for step in spacing.steps_emu
        )
        return f'<div class="steps-scale">{bars}</div>'

    def anatomy(self) -> str:
        grid = self.ds.grid
        margins = grid.margins
        width, height = grid.width_emu, grid.height_emu
        columns = "".join(
            f'<i style="width: {_pct(grid.column_width_emu, grid.content_width_emu)}; '
            f"background: {self.p.ref(ColorRef.ACCENT1)}; opacity: .18; "
            f'margin-right: {_pct(grid.gutter_emu, grid.content_width_emu)}"></i>'
            for _ in range(grid.columns)
        )
        #: Поля рисуются заливкой, а не подписью внутри: верхнее поле бывает в 2 % высоты
        #: слайда, и любая строка в нём вылезла бы наружу. Слова — в подписи под схемой.
        bands = "".join(
            (
                f'<div class="zone margin" style="left: 0; top: 0; height: 100%; '
                f'width: {_pct(margins.left, width)}"></div>',
                f'<div class="zone margin" style="right: 0; top: 0; height: 100%; '
                f'width: {_pct(margins.right, width)}"></div>',
                f'<div class="zone margin" style="left: 0; top: 0; width: 100%; '
                f'height: {_pct(margins.top, height)}"></div>',
                f'<div class="zone margin" style="left: 0; bottom: 0; width: 100%; '
                f'height: {_pct(margins.bottom, height)}"></div>',
            )
        )
        return (
            f'<div class="slide-map" style="aspect-ratio: {width} / {height}">'
            f"{bands}"
            f'<div class="zone content" style="left: {_pct(margins.left, width)}; '
            f"top: {_pct(margins.top, height)}; width: {_pct(grid.content_width_emu, width)}; "
            f'height: {_pct(grid.content_height_emu, height)}">'
            f'<div class="cols">{columns}</div><span>зона контента</span></div></div>'
            f'<p class="lede">Заливкой — поля шаблона: сверху {_esc(_cm(margins.top))}, '
            f"снизу {_esc(_cm(margins.bottom))}, слева {_esc(_cm(margins.left))}, "
            f"справа {_esc(_cm(margins.right))}. Пунктиром — зона контента между ними, "
            f"полосами — {grid.columns} колонок по {_esc(_cm(grid.column_width_emu))} "
            f"с межколонником {_esc(_cm(grid.gutter_emu))}. {self.band_notes()}</p>"
        )

    def band_notes(self) -> str:
        """Что шаблон держит в верхнем и нижнем поле — словами достроенных элементов."""
        elements = {item.kind: item for item in self.group("элементы")}
        notes = [
            f"{_esc(item.title)}: {_esc(item.purpose)}."
            for kind in ("header", "footer")
            if (item := elements.get(kind)) is not None
        ]
        return " ".join(notes)

    def rules(self) -> str:
        return (
            f'<ul class="rules">{"".join(self.rule(rule) for rule in self.ds.assembly_rules)}</ul>'
        )

    def rule(self, rule: AssemblyRule) -> str:
        value = _cm(int(rule.value)) if rule.unit == "emu" else f"{_num(rule.value, 1)} {rule.unit}"
        return (
            f"<li>{_esc(rule.text)} — <b>{_esc(value)}</b> "
            f"<span>источник: {_esc(rule.source)}</span> {_origin_tag(rule.origin)}</li>"
        )
