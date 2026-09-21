"""Привязка к теме: `ColorRef` → `MSO_THEME_COLOR`, `FontRef` → гарнитура темы (ADR-002).

Единственное место, где IR-ссылки превращаются в свойства python-pptx. Ни RGB, ни имени
гарнитуры здесь не появляется: смена шаблона обязана перекрашивать и перешрифтовывать
колоду без правки кода.
"""

from __future__ import annotations

from pptx.dml.fill import FillFormat
from pptx.dml.line import LineFormat
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.text.text import Font

from deckforge.domain.enums import ColorRef, FontRef
from deckforge.domain.template import TemplateManifest

THEME_COLORS: dict[ColorRef, MSO_THEME_COLOR] = {
    ColorRef.DK1: MSO_THEME_COLOR.DARK_1,
    ColorRef.LT1: MSO_THEME_COLOR.LIGHT_1,
    ColorRef.DK2: MSO_THEME_COLOR.DARK_2,
    ColorRef.LT2: MSO_THEME_COLOR.LIGHT_2,
    ColorRef.ACCENT1: MSO_THEME_COLOR.ACCENT_1,
    ColorRef.ACCENT2: MSO_THEME_COLOR.ACCENT_2,
    ColorRef.ACCENT3: MSO_THEME_COLOR.ACCENT_3,
    ColorRef.ACCENT4: MSO_THEME_COLOR.ACCENT_4,
    ColorRef.ACCENT5: MSO_THEME_COLOR.ACCENT_5,
    ColorRef.ACCENT6: MSO_THEME_COLOR.ACCENT_6,
    ColorRef.HLINK: MSO_THEME_COLOR.HYPERLINK,
    ColorRef.FOL_HLINK: MSO_THEME_COLOR.FOLLOWED_HYPERLINK,
}

#: Как слот темы называется в атрибуте `a:schemeClr/@val`. Имена там свои: тёмный
#: и светлый слоты в слайде зовутся `tx1`/`bg1`, а не `dk1`/`lt1`.
_SCHEME_TOKENS: dict[ColorRef, str] = {
    ColorRef.DK1: "tx1",
    ColorRef.LT1: "bg1",
    ColorRef.DK2: "tx2",
    ColorRef.LT2: "bg2",
    ColorRef.ACCENT1: "accent1",
    ColorRef.ACCENT2: "accent2",
    ColorRef.ACCENT3: "accent3",
    ColorRef.ACCENT4: "accent4",
    ColorRef.ACCENT5: "accent5",
    ColorRef.ACCENT6: "accent6",
    ColorRef.HLINK: "hlink",
    ColorRef.FOL_HLINK: "folHlink",
}


def scheme_token(ref: ColorRef) -> str:
    """Значение `a:schemeClr/@val` для слота темы — там, где python-pptx не помогает."""
    return _SCHEME_TOKENS[ref]


#: Ссылки на шрифты темы в `a:latin/@typeface`: PowerPoint подставляет гарнитуру темы сам.
_FONT_TOKENS: dict[FontRef, str] = {
    FontRef.MAJOR_LATIN: "+mj-lt",
    FontRef.MINOR_LATIN: "+mn-lt",
    FontRef.MAJOR_CS: "+mj-cs",
    FontRef.MINOR_CS: "+mn-cs",
}

_LATIN_PAIR = {
    FontRef.MAJOR_CS: FontRef.MAJOR_LATIN,
    FontRef.MINOR_CS: FontRef.MINOR_LATIN,
}


def apply_theme_color(font_or_fill: object, ref: ColorRef) -> None:
    """Ставит ссылку на цвет темы, а не RGB — иначе смена шаблона не перекрасит объект."""
    theme_color = THEME_COLORS[ref]
    if isinstance(font_or_fill, Font):
        font_or_fill.color.theme_color = theme_color
    elif isinstance(font_or_fill, FillFormat):
        font_or_fill.solid()  # type: ignore[no-untyped-call]
        font_or_fill.fore_color.theme_color = theme_color
    elif isinstance(font_or_fill, LineFormat):
        font_or_fill.color.theme_color = theme_color
    else:
        raise TypeError(f"цвет темы ставится шрифту, заливке или линии, а не {type(font_or_fill)}")


def theme_font_token(ref: FontRef) -> str:
    """Значение `typeface`, ссылающееся на шрифт темы, а не на конкретную гарнитуру."""
    return _FONT_TOKENS[ref]


#: Обратное соответствие: по токену в файле — ссылка на шрифт темы.
_REF_BY_TOKEN = {token: ref for ref, token in _FONT_TOKENS.items()}


def font_family_for_token(token: str, manifest: TemplateManifest) -> str | None:
    """«+mn-lt» → гарнитура темы, всё остальное → `None`.

    В готовом файле `typeface` может быть не названием шрифта, а ссылкой на тему:
    так пишет и PowerPoint, и наш текстбокс. Тот, кто читает файл и не знает об этом,
    принимает ссылку за чужую гарнитуру — отсюда ошибка «+mn-lt в шаблоне не встречается»
    на каждом прогоне «Шаблона 2024».
    """
    ref = _REF_BY_TOKEN.get(token.strip().lower())
    return resolve_font(ref, manifest) if ref is not None else None


def resolve_font(ref: FontRef, manifest: TemplateManifest) -> str:
    """Имя гарнитуры из манифеста — для метрик и html, не для записи в pptx."""
    fonts = manifest.theme.fonts
    return fonts.get(ref) or fonts.get(_LATIN_PAIR.get(ref, ref)) or fonts.minor_latin
