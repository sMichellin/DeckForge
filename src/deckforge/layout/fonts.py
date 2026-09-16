"""Где взять файл шрифта для метрик. Change (12) `layout-fitting`.

`fontTools` меряет файл, а не имя из манифеста. Шрифта шаблона в системе чаще всего нет:
в пакете он лежит сжатым EOT (MicroType Express), который не открыть, а слой `layout`
файла шаблона и не видит (ADR-003). Поэтому замена — основной режим, а не крайний случай.

Замена **пессимистичная**: верхний квартиль по ширине среди обычных гарнитур с кириллицей.
Цена ошибок несимметрична — лишняя ступень кегля остаётся косметикой, а вылезший текст
ломает слайд. Квартиль, а не максимум: одна декоративная гарнитура в системе не должна
срезать кегль всей колоды.
"""

from __future__ import annotations

import logging
import math
import os
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from fontTools.ttLib import (  # type: ignore[import-untyped]
    TTCollection,
    TTFont,
    TTLibError,
)

from deckforge.config import ASSETS_DIR

FONT_DIRS_ENV = "DECKFORGE_FONT_DIRS"
_FONT_SUFFIXES = frozenset({".ttf", ".otf", ".ttc"})

#: `usWidthClass` нормальной ширины по спецификации OpenType.
_WIDTH_CLASS_NORMAL = 5
#: Граница «жирного» по `usWeightClass`: 600 — SemiBold.
_BOLD_WEIGHT = 600
_FS_SELECTION_ITALIC = 1 << 0
_FS_SELECTION_BOLD = 1 << 5
#: Какая доля кандидатов уже замены: 0,75 — верхний квартиль.
_FALLBACK_QUANTILE = 0.75


def _alphabet(first: str, last: str) -> str:
    return "".join(chr(c) for c in range(ord(first), ord(last) + 1))


#: Пробная строка для выбора замены: алфавиты, которыми пишутся колоды, и цифры.
#: Это не константа шаблона — набор знаков одинаков для любого шаблона.
PROBE_TEXT = (
    _alphabet("а", "я") + _alphabet("А", "Я") + "ёЁ" + _alphabet("a", "z") + _alphabet("A", "Z")
    + _alphabet("0", "9")
)


class FontNotFoundError(LookupError):
    """Ни одного пригодного шрифта: считать метрики не по чему, гадать нельзя."""


@dataclass(frozen=True, slots=True)
class FontFace:
    """Одно начертание в файле шрифта (`.ttc` содержит несколько)."""

    path: Path
    font_number: int
    family: str
    #: Семейство из name ID 1: у «Arial Narrow» это «Arial Narrow», а `family` — «Arial».
    legacy_family: str
    aliases: frozenset[str]
    bold: bool
    italic: bool
    weight: int
    width_class: int
    fixed_pitch: bool


@dataclass(frozen=True, slots=True)
class ResolvedFont:
    face: FontFace
    #: `True` — найдена гарнитура шаблона; `False` — считаем по пессимистичной замене.
    exact: bool


@dataclass(frozen=True, slots=True)
class FontMetrics:
    """Ширины знаков в долях кегля (em)."""

    advances_em: dict[int, float] = field(repr=False)
    #: Ширина знака, которого в шрифте нет. Рендер возьмёт его из другой гарнитуры,
    #: поэтому `.notdef` (часто узкий или нулевой) занизил бы строку.
    missing_em: float

    def covers(self, text: str) -> bool:
        return all(ord(ch) in self.advances_em for ch in text if not ch.isspace())

    def advance_em(self, ch: str) -> float:
        return self.advances_em.get(ord(ch), self.missing_em)

    def text_width_em(self, text: str) -> float:
        return sum(self.advance_em(ch) for ch in text)


def _read_face(font: TTFont, path: Path, number: int) -> FontFace | None:
    if "name" not in font or "OS/2" not in font:
        return None
    name = font["name"]
    typographic = name.getDebugName(16)
    legacy = name.getDebugName(1)
    family = typographic or legacy
    if not family:
        return None
    os2 = font["OS/2"]
    fixed = bool(font["post"].isFixedPitch) if "post" in font else False
    return FontFace(
        path=path,
        font_number=number,
        family=family,
        legacy_family=legacy or family,
        aliases=frozenset(n.casefold() for n in (typographic, legacy) if n),
        bold=bool(os2.fsSelection & _FS_SELECTION_BOLD) or os2.usWeightClass >= _BOLD_WEIGHT,
        italic=bool(os2.fsSelection & _FS_SELECTION_ITALIC),
        weight=os2.usWeightClass,
        width_class=os2.usWidthClass,
        fixed_pitch=fixed,
    )


def _faces_in_file(path: Path) -> list[FontFace]:
    try:
        if path.suffix.lower() == ".ttc":
            fonts = TTCollection(str(path), lazy=True).fonts
        else:
            fonts = [TTFont(str(path), lazy=True)]
        faces = [_read_face(font, path, number) for number, font in enumerate(fonts)]
    except (TTLibError, OSError, KeyError, AssertionError, ValueError, IndexError):
        # Битый или экзотический файл не должен ронять вёрстку всей колоды.
        return []
    return [face for face in faces if face is not None]


@contextmanager
def _quiet_fonttools() -> Iterator[None]:
    """fontTools пишет в лог предупреждение на каждый слегка нестандартный файл; при обходе
    системного каталога это сотни строк шума."""
    log = logging.getLogger("fontTools")
    level = log.level
    log.setLevel(logging.ERROR)
    try:
        yield
    finally:
        log.setLevel(level)


@cache
def _faces_in_dir(directory: Path) -> tuple[FontFace, ...]:
    if not directory.is_dir():
        return ()
    files = sorted(p for p in directory.rglob("*") if p.suffix.lower() in _FONT_SUFFIXES)
    with _quiet_fonttools():
        return tuple(face for path in files for face in _faces_in_file(path))


@cache
def _load_metrics(path: Path, font_number: int) -> FontMetrics | None:
    """Метрики начертания или `None`, если файл не читается.

    Индекс смотрит только `name` и `OS/2`, поэтому файл с испорченными `cmap`/`hmtx` в него
    попадает. Один такой файл в системном каталоге не должен ронять вёрстку колоды.
    """
    try:
        with _quiet_fonttools():
            font = TTFont(str(path), fontNumber=font_number, lazy=True)
            upm = font["head"].unitsPerEm
            hmtx = font["hmtx"]
            cmap = font.getBestCmap() or {}
            notdef = hmtx[".notdef"][0] / upm if ".notdef" in hmtx.metrics else 0.0
            advances = {
                cp: hmtx[glyph][0] / upm for cp, glyph in cmap.items() if glyph in hmtx.metrics
            }
    except Exception:
        # fontTools на повреждённых таблицах бросает что угодно, от struct.error до KeyError.
        return None
    letters = [advances[ord(ch)] for ch in PROBE_TEXT if ord(ch) in advances]
    typical = sum(letters) / len(letters) if letters else notdef
    return FontMetrics(advances_em=advances, missing_em=max(notdef, typical))


def system_font_dirs() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        windir = Path(os.environ.get("WINDIR", "C:/Windows"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return [windir / "Fonts", local / "Microsoft" / "Windows" / "Fonts"]
    if sys.platform == "darwin":
        return [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library" / "Fonts"]
    return [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        home / ".local" / "share" / "fonts",
        home / ".fonts",
    ]


class FontLibrary:
    """Каталоги шрифтов в порядке приоритета. Индекс строится лениво и кэшируется."""

    def __init__(self, dirs: Iterable[Path]) -> None:
        self.dirs: tuple[Path, ...] = tuple(dict.fromkeys(Path(d) for d in dirs))
        self._fallback: dict[bool, FontFace] = {}

    @classmethod
    def default(cls) -> FontLibrary:
        """`DECKFORGE_FONT_DIRS` → `assets/fonts` → системные каталоги."""
        env = [Path(p) for p in os.environ.get(FONT_DIRS_ENV, "").split(os.pathsep) if p]
        return cls([*env, ASSETS_DIR / "fonts", *system_font_dirs()])

    def faces(self) -> Iterable[FontFace]:
        for directory in self.dirs:
            yield from _faces_in_dir(directory)

    def metrics(self, face: FontFace) -> FontMetrics:
        metrics = _load_metrics(face.path, face.font_number)
        if metrics is None:
            raise FontNotFoundError(f"метрики не читаются: {face.path}")
        return metrics

    def _readable(self, face: FontFace) -> bool:
        return _load_metrics(face.path, face.font_number) is not None

    def resolve(self, family: str, *, bold: bool = False, italic: bool = False) -> ResolvedFont:
        wanted = family.strip().casefold()
        # Каталоги по порядку: гарнитура из `DECKFORGE_FONT_DIRS` важнее системной тёзки,
        # и системный каталог не сканируется, если шрифт нашёлся раньше.
        for directory in self.dirs:
            same_family = [
                f for f in _faces_in_dir(directory) if wanted in f.aliases and self._readable(f)
            ]
            if same_family:
                return ResolvedFont(_closest_style(same_family, wanted, bold, italic), exact=True)
        return ResolvedFont(self._fallback_face(bold), exact=False)

    def _fallback_face(self, bold: bool) -> FontFace:
        if bold not in self._fallback:
            self._fallback[bold] = self._pick_fallback(bold)
        return self._fallback[bold]

    def _suitable(self, faces: Iterable[FontFace], bold: bool) -> list[FontFace]:
        plain = [
            f for f in faces
            if f.width_class == _WIDTH_CLASS_NORMAL and not f.fixed_pitch and not f.italic
            and self._readable(f) and self.metrics(f).covers(PROBE_TEXT)
        ]
        return [f for f in plain if f.bold == bold] or plain

    def _pick_fallback(self, bold: bool) -> FontFace:
        # Источник замены — первый каталог, где есть подходящие гарнитуры: так
        # `DECKFORGE_FONT_DIRS` и `assets/fonts` задают её воспроизводимо на любой машине.
        pool = next(
            (found for d in self.dirs if (found := self._suitable(_faces_in_dir(d), bold))),
            None,
        )
        if pool is None:
            # Нет ни одной обычной гарнитуры с кириллицей — лучше мерить хоть чем-то читаемым,
            # чем не мерить вовсе.
            pool = [f for f in self.faces() if self._readable(f)]
        if not pool:
            raise FontNotFoundError(
                f"нет ни одного шрифта в каталогах {[str(d) for d in self.dirs]}; "
                f"задайте {FONT_DIRS_ENV}"
            )
        ranked = sorted(
            pool,
            key=lambda f: (self.metrics(f).text_width_em(PROBE_TEXT), str(f.path), f.font_number),
        )
        return ranked[math.ceil(_FALLBACK_QUANTILE * len(ranked)) - 1]


def _closest_style(
    faces: Sequence[FontFace], wanted: str, bold: bool, italic: bool
) -> FontFace:
    target_weight = _BOLD_WEIGHT + 100 if bold else 400
    return min(
        faces,
        key=lambda f: (
            f.bold != bold,
            f.italic != italic,
            # «Arial Narrow» и «Arial Black» числятся в типографском семействе «Arial».
            f.width_class != _WIDTH_CLASS_NORMAL and f.legacy_family.casefold() != wanted,
            abs(f.weight - target_weight),
            str(f.path),
            f.font_number,
        ),
    )
