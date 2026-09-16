"""Поиск файла шрифта и пессимистичная замена. Change (12) `layout-fitting`.

Шрифты собираются здесь же `fontTools.fontBuilder` с известными ширинами знаков:
тесты не зависят от того, какие шрифты стоят на машине разработчика или в CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from deckforge.layout.fonts import FontLibrary, FontNotFoundError

UPM = 1000

#: Знаки синтетического шрифта: латиница, кириллица, цифры, пунктуация и пробел.
CHARS = (
    [chr(c) for c in range(ord("a"), ord("z") + 1)]
    + [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [chr(c) for c in range(ord("а"), ord("я") + 1)]
    + [chr(c) for c in range(ord("А"), ord("Я") + 1)]
    + list("ёЁ0123456789.,:;!?%()-–—«»\"'/+ ")
)
LATIN_ONLY = [c for c in CHARS if not ("а" <= c.lower() <= "я" or c in "ёЁ")]


def make_font(
    directory: Path,
    family: str,
    *,
    advance: int = 500,
    space: int | None = None,
    bold: bool = False,
    italic: bool = False,
    width_class: int = 5,
    fixed_pitch: bool = False,
    chars: list[str] | None = None,
    typographic_family: str | None = None,
    notdef_advance: int | None = None,
) -> Path:
    """Шрифт, в котором каждый знак шириной `advance` единиц из `UPM`."""
    chars = CHARS if chars is None else chars
    names = [".notdef"] + [f"uni{ord(c):04X}" for c in chars]
    empty = TTGlyphPen(None).glyph()

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({ord(c): f"uni{ord(c):04X}" for c in chars})
    fb.setupGlyf({n: empty for n in names})
    metrics = {n: (advance, 0) for n in names}
    if notdef_advance is not None:
        metrics[".notdef"] = (notdef_advance, 0)
    if space is not None and " " in chars:
        metrics["uni0020"] = (space, 0)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    style = ("Bold " if bold else "") + ("Italic" if italic else "")
    style = style.strip() or "Regular"
    names_table = {"familyName": family, "styleName": style}
    if typographic_family:
        names_table["typographicFamily"] = typographic_family
    fb.setupNameTable(names_table)
    fs_selection = (0x20 if bold else 0) | (0x01 if italic else 0) or 0x40
    fb.setupOS2(
        usWeightClass=700 if bold else 400,
        usWidthClass=width_class,
        fsSelection=fs_selection,
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
    )
    fb.setupPost(isFixedPitch=int(fixed_pitch))
    path = directory / f"{family.replace(' ', '')}-{style.replace(' ', '')}.ttf"
    fb.save(str(path))
    return path


@pytest.fixture
def font_dir(tmp_path: Path) -> Path:
    make_font(tmp_path, "Deck Sans", advance=500)
    make_font(tmp_path, "Deck Sans", advance=560, bold=True)
    return tmp_path


def test_exact_family_is_found_case_insensitively(font_dir: Path) -> None:
    lib = FontLibrary([font_dir])
    resolved = lib.resolve("deck sans")
    assert resolved.exact
    assert resolved.face.family == "Deck Sans"
    assert resolved.face.bold is False


def test_bold_face_is_preferred_when_bold_requested(font_dir: Path) -> None:
    resolved = FontLibrary([font_dir]).resolve("Deck Sans", bold=True)
    assert resolved.exact
    assert resolved.face.bold is True


def test_missing_style_falls_back_to_the_same_family(font_dir: Path) -> None:
    """Курсива нет — берём прямое начертание той же гарнитуры, это всё ещё точный шрифт."""
    resolved = FontLibrary([font_dir]).resolve("Deck Sans", italic=True)
    assert resolved.exact
    assert resolved.face.family == "Deck Sans"


def test_width_variants_of_a_family_do_not_replace_the_regular_face(tmp_path: Path) -> None:
    """У «Arial Narrow» типографское семейство тоже «Arial»: узкий файл не должен
    выиграть у обычного только потому, что его имя раньше по алфавиту."""
    make_font(tmp_path, "AAA Narrow", advance=300, width_class=3, typographic_family="Deck")
    regular = make_font(tmp_path, "Deck", advance=500)
    resolved = FontLibrary([tmp_path]).resolve("Deck")
    assert resolved.exact
    assert resolved.face.path == regular


def test_width_variant_is_still_found_by_its_own_name(tmp_path: Path) -> None:
    narrow = make_font(tmp_path, "Deck Narrow", advance=300, width_class=3,
                       typographic_family="Deck")
    make_font(tmp_path, "Deck", advance=500)
    assert FontLibrary([tmp_path]).resolve("Deck Narrow").face.path == narrow


def test_missing_family_takes_the_wider_font(tmp_path: Path) -> None:
    make_font(tmp_path, "Narrow Grotesk", advance=450)
    wide = make_font(tmp_path, "Wide Grotesk", advance=600)
    resolved = FontLibrary([tmp_path]).resolve("Шрифт, которого нет")
    assert not resolved.exact
    assert resolved.face.path == wide


def test_fallback_is_robust_to_a_single_exotic_wide_font(tmp_path: Path) -> None:
    """Верхний квартиль, а не максимум: одна декоративная гарнитура в системе
    не должна срезать кегль всей колоды."""
    make_font(tmp_path, "Grotesk A", advance=450)
    make_font(tmp_path, "Grotesk B", advance=500)
    upper = make_font(tmp_path, "Grotesk C", advance=550)
    make_font(tmp_path, "Display Wide", advance=1200)
    assert FontLibrary([tmp_path]).resolve("Нет такого").face.path == upper


def test_fallback_comes_from_the_first_source_that_has_fonts(tmp_path: Path) -> None:
    """Каталог из `DECKFORGE_FONT_DIRS` или `assets/fonts` задаёт замену воспроизводимо,
    независимо от того, что стоит в системе конкретной машины."""
    pinned, system = tmp_path / "pinned", tmp_path / "system"
    pinned.mkdir()
    system.mkdir()
    chosen = make_font(pinned, "Pinned", advance=500)
    make_font(system, "System Wide", advance=700)
    assert FontLibrary([pinned, system]).resolve("Нет такого").face.path == chosen


def test_fallback_ignores_condensed_monospace_and_italic_fonts(tmp_path: Path) -> None:
    """Иначе замена выбрала бы экзотику и зря срезала кегль на всей колоде."""
    regular = make_font(tmp_path, "Plain", advance=500)
    make_font(tmp_path, "Expanded", advance=900, width_class=7)
    make_font(tmp_path, "Mono", advance=900, fixed_pitch=True)
    make_font(tmp_path, "Slanted", advance=900, italic=True)
    assert FontLibrary([tmp_path]).resolve("Нет такого").face.path == regular


def test_fallback_requires_cyrillic_coverage(tmp_path: Path) -> None:
    make_font(tmp_path, "Latin Wide", advance=900, chars=LATIN_ONLY)
    full = make_font(tmp_path, "Full", advance=500)
    assert FontLibrary([tmp_path]).resolve("Нет такого").face.path == full


def test_fallback_is_deterministic(tmp_path: Path) -> None:
    make_font(tmp_path, "Twin A", advance=500)
    make_font(tmp_path, "Twin B", advance=500)
    first = FontLibrary([tmp_path]).resolve("Нет").face.path
    assert all(FontLibrary([tmp_path]).resolve("Нет").face.path == first for _ in range(3))


def test_empty_library_is_an_error_not_a_guess(tmp_path: Path) -> None:
    with pytest.raises(FontNotFoundError):
        FontLibrary([tmp_path]).resolve("Что угодно")


def test_env_dirs_come_first(monkeypatch: pytest.MonkeyPatch, font_dir: Path) -> None:
    monkeypatch.setenv("DECKFORGE_FONT_DIRS", str(font_dir))
    library = FontLibrary.default()
    assert library.dirs[0] == font_dir
    assert library.resolve("Deck Sans").exact


def test_earlier_dir_wins_for_the_same_family(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    chosen = make_font(first, "Deck Sans", advance=500)
    make_font(second, "Deck Sans", advance=700)
    assert FontLibrary([first, second]).resolve("Deck Sans").face.path == chosen


def test_broken_font_file_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "broken.ttf").write_bytes(b"not a font")
    make_font(tmp_path, "Deck Sans")
    assert FontLibrary([tmp_path]).resolve("Deck Sans").exact


def break_cmap(path: Path) -> None:
    """Портит таблицу cmap, оставляя `name` и `OS/2` целыми: индекс файл примет,
    а метрики прочитать не получится."""
    from fontTools.ttLib import TTFont

    font = TTFont(str(path))
    data = bytearray(path.read_bytes())
    entry = font.reader.tables["cmap"]
    data[entry.offset : entry.offset + entry.length] = bytes([0xFF]) * entry.length
    path.write_bytes(bytes(data))


def test_font_with_broken_metrics_is_skipped_by_fallback(tmp_path: Path) -> None:
    good = make_font(tmp_path, "Good", advance=500)
    break_cmap(make_font(tmp_path, "Broken", advance=900))
    assert FontLibrary([tmp_path]).resolve("Нет такого").face.path == good


def test_exact_font_with_broken_metrics_falls_back(tmp_path: Path) -> None:
    make_font(tmp_path, "Good", advance=500)
    break_cmap(make_font(tmp_path, "Deck Sans", advance=900))
    resolved = FontLibrary([tmp_path]).resolve("Deck Sans")
    assert not resolved.exact


def test_advance_widths_are_read_per_em(font_dir: Path) -> None:
    face = FontLibrary([font_dir]).resolve("Deck Sans").face
    metrics = FontLibrary([font_dir]).metrics(face)
    assert metrics.advance_em("Ж") == pytest.approx(0.5)
    assert metrics.text_width_em("аб") == pytest.approx(1.0)
