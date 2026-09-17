"""Контент-пакет → `ContentPackage`. Change (7) `content-ingestion`.

Числа извлекаются детерминированно и получают `fact_id` — якорь фактчекинга (§5.2).

Три решения модуля продиктованы живым прогоном, а не рассуждением
(`openspec/changes/content-ingestion/proposal.md`, раздел Explore):

* датасеты читаются из `.xlsx` **напрямую**: через markitdown год приходит как `2025.0`,
  пустая ячейка как `NaN`, безымянный столбец как `Unnamed: 1`;
* шапка таблицы восстанавливается из первой непустой строки: markitdown отдаёт первую
  строку таблицы `.docx` пустой, а настоящие заголовки — телом таблицы;
* пробелы схлопываются, а разорванные абзацы склеиваются до разбора: PDF отдаёт
  заголовок по слову на абзац и двойные пробелы внутри предложений.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from deckforge.domain.content import (
    Asset,
    Brief,
    ContentPackage,
    Dataset,
    Fact,
    Number,
    Series,
)

NBSP: Final = " "
NARROW_NBSP: Final = " "
MINUS: Final = "−"

#: Пробелы, встречающиеся внутри числа: обычный, табуляция, неразрывный, узкий неразрывный.
_SP: Final = f"[ \t{NBSP}{NARROW_NBSP}]"

#: Ядро числа: разряды через пробел либо сплошная запись, дробная часть через запятую или точку.
_NUM: Final = rf"\d{{1,3}}(?:{_SP}\d{{3}})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"

#: Знак вместе с возможным пробелом после него. Только дефис и типографский минус:
#: короткое тире разделяет диапазон. Группа целиком необязательна — иначе
#: необязательный пробел съедает пробел перед числом, `raw` уезжает на символ влево,
#: и совпадение начинается раньше, чем успевают сработать ловушки даты и диапазона.
_SIGN: Final = rf"(?:[-{MINUS}]{_SP}?)?"

_SCALE: Final = r"тыс\.?|млн\.?|млрд\.?|трлн\.?"
_CURRENCY: Final = r"₽|руб\.?|долл\.?|\$|€"
_PP: Final = rf"п\.?{_SP}?п\.?"

#: Порядок альтернатив значим: сначала ловушки, затем числа с единицей, в конце голые.
_MASTER: Final = re.compile(
    rf"""
    (?P<date>\b\d{{1,2}}\.\d{{1,2}}\.\d{{2,4}}\b)
  | (?P<version>\bv\.?{_SP}?\d+(?:\.\d+)*\b)
  | (?P<time>\b\d{{1,2}}:\d{{2}}(?::\d{{2}})?\b)
  | (?P<ratio>\b\d+{_SP}?/{_SP}?\d+\b)
  | (?P<range>(?P<range_low>{_NUM}){_SP}*[–—]{_SP}*(?P<range_high>{_NUM})
              (?:{_SP}*(?P<range_unit>%|{_PP}))?)
  | (?P<multx>\b[xх]{_SP}?(?P<multx_num>{_NUM}))
  | (?P<multraz>\bв{_SP}+(?P<multraz_num>{_NUM}){_SP}+раз(?:а|ов)?\b)
  | (?P<pp>{_SIGN}(?P<pp_num>{_NUM}){_SP}*{_PP})
  | (?P<pct>{_SIGN}(?P<pct_num>{_NUM}){_SP}*%)
  | (?P<money>{_SIGN}(?P<money_num>{_NUM})
              (?:{_SP}*(?P<scale>{_SCALE}))?{_SP}*(?P<currency>{_CURRENCY}))
  | (?P<bare>{_SIGN}(?P<bare_num>{_NUM}))
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: Альтернативы в порядке объявления: имя группы = вид совпадения.
_KINDS: Final = (
    "date",
    "time",
    "version",
    "ratio",
    "range",
    "multx",
    "multraz",
    "pp",
    "pct",
    "money",
    "bare",
)

#: Ловушки: в тексте факта остаются, числами-фактами не становятся.
_NOT_A_MEASUREMENT: Final = frozenset({"date", "time", "version", "ratio"})

#: Четырёхзначное целое в этих границах без единицы — год, а не измеренная величина.
_YEAR_RANGE: Final = range(1900, 2100)


def _to_float(raw: str) -> float:
    """«1 200,5» → 1200.5. Пробелы любых видов внутри числа — разделители разрядов."""
    for space in (NBSP, NARROW_NBSP, " ", "\t"):
        raw = raw.replace(space, "")
    return float(raw.replace(",", "."))


def _is_year(digits: str) -> bool:
    return digits.isdigit() and len(digits) == 4 and int(digits) in _YEAR_RANGE


def _kind_of(match: re.Match[str]) -> str:
    return next(name for name in _KINDS if match.group(name) is not None)


def _unit_of(match: re.Match[str], kind: str) -> str | None:
    if kind in {"multx", "multraz"}:
        return "x"
    if kind == "pp":
        return "п.п."
    if kind == "pct":
        return "%"
    if kind == "money":
        scale = (match.group("scale") or "").strip().rstrip(".")
        currency = (match.group("currency") or "").strip().rstrip(".")
        return f"{scale} {currency}".strip()
    if kind == "range":
        raw_unit = match.group("range_unit")
        if raw_unit is None:
            return None
        return "%" if "%" in raw_unit else "п.п."
    return None


def extract_numbers(text: str, language: str = "ru") -> list[Number]:
    """«37,5 %», «1 200 млн ₽», «x2.3» → нормализованные `Number` с сохранением `raw`.

    `raw` хранит исходное написание символ в символ: на нём держится фактчекинг
    `content.numbers_grounded` и разрешение форматных расхождений («37 %» против «0.37»).

    Годы, версии, даты и режимы вида «24/7» числами-фактами не считаются: иначе аудит
    будет сверять с источником номера версий. В тексте факта они остаются.
    """
    if language != "ru":
        raise ValueError(f"извлечение чисел пока только для русского, получено {language!r}")

    numbers: list[Number] = []
    for match in _MASTER.finditer(text):
        kind = _kind_of(match)
        if kind in _NOT_A_MEASUREMENT:
            continue
        raw = match.group(0)
        unit = _unit_of(match, kind)
        if kind == "range":
            for edge in ("range_low", "range_high"):
                numbers.append(Number(value=_to_float(match.group(edge)), unit=unit, raw=raw))
            continue
        digits = match.group(f"{kind}_num")
        if kind == "bare" and _is_year(digits):
            continue
        value = _to_float(digits)
        if raw.lstrip().startswith(("-", MINUS)):
            value = -value
        numbers.append(Number(value=value, unit=unit, raw=raw))
    return numbers


class ContentIngestionError(RuntimeError):
    """Контент-пакет непригоден. Явный отказ лучше тихо пустого результата."""


_TEXT_SUFFIXES: Final = frozenset({".md", ".markdown", ".txt"})
_CONVERTIBLE: Final = frozenset({".docx", ".doc", ".pdf", ".pptx", ".html", ".htm", ".rtf"})
_WORKBOOK: Final = frozenset({".xlsx", ".xlsm", ".csv"})
_IMAGE: Final = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})

#: Меньше этого числа букв в PDF — скан без текстового слоя, а не пустой документ.
_MIN_LETTERS_IN_PDF: Final = 100

#: Строка, начинающая структуру markdown: заголовок, пункт списка, строка таблицы.
_STRUCTURAL: Final = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|\|)")

#: Конец предложения. Двоеточие и точка с запятой не считаются: в рваном PDF
#: заголовок «Аналитическая записка: рынок…» иначе остаётся разрезанным.
_SENTENCE_END: Final = (".", "!", "?", ".»", "!»", "?»", '."', '!"', '?"')

_SENTENCE_SPLIT: Final = re.compile(r"(?<=[.!?])\s+(?=[«\"(]?[А-ЯЁA-Z0-9])")
_MD_DECORATION: Final = re.compile(r"(\*\*|__|\*|`|\\)")
_MD_PREFIX: Final = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)")
_UNIT_IN_TITLE: Final = re.compile(r"[,(]\s*([^,()]{1,20}?)\s*\)?\s*$")
_TOTALS: Final = frozenset({"итого", "всего", "total", "сумма"})


def _starts_with_capital(line: str) -> bool:
    """Строка с заглавной буквы начинает новый абзац, а не продолжает прошлый.

    Без этого правила склейка не останавливается нигде: в рваном PDF ни заголовок,
    ни его обрывки не кончаются точкой, и первый абзац текста прилипает к заголовку.

    Цифра новый абзац **не** начинает: PDF переносит строку где угодно, в том числе
    перед числом («оценивается в / 48,3 млрд ₽»), и по цифре предложение бы рвалось
    пополам. Нумерованный список сюда не попадает — его ловит `_STRUCTURAL`.
    """
    first = next((ch for ch in line if ch.isalpha()), "")
    return first.isupper()


def _normalize(text: str) -> str:
    """Схлопывает кратные пробелы и склеивает абзацы, разорванные конвертацией PDF.

    Неразрывные пробелы не трогаются: они часть записи числа.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for raw_line in text.split("\n"):
        line = re.sub(r"[ \t]{2,}", " ", raw_line).strip()
        if not line:
            continue
        starts_new_paragraph = (
            not out
            or _STRUCTURAL.match(line) is not None
            or _STRUCTURAL.match(out[-1]) is not None
            or out[-1].endswith(_SENTENCE_END)
            or _starts_with_capital(line)
        )
        if starts_new_paragraph:
            out.append(line)
        else:
            out[-1] = f"{out[-1]} {line}"
    return "\n".join(out)


def _plain_text(line: str) -> str:
    return _MD_DECORATION.sub("", _MD_PREFIX.sub("", line)).strip()


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


def _cell_to_str(value: Any) -> str:
    """«2025.0» из Excel и markitdown обязано стать «2025», иначе шапка датасета врёт."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _cell_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    numbers = extract_numbers(str(value))
    return numbers[0].value if len(numbers) == 1 else None


def _is_blank_row(row: list[Any]) -> bool:
    return all(_cell_to_str(cell) in {"", "NaN", "None"} for cell in row)


def _dataset_from_rows(
    rows: list[list[Any]], dataset_id: str, default_title: str, source_ref: str
) -> Dataset | None:
    """Строки таблицы → `Dataset`. Шапка ищется, а не берётся первой строкой.

    markitdown отдаёт первую строку таблицы `.docx` пустой, а настоящие заголовки —
    телом таблицы. Excel добавляет строку заголовка листа и пустые строки-разделители.
    """
    meaningful = [row for row in rows if not _is_blank_row(row)]
    if len(meaningful) < 3:
        return None

    title = default_title
    if sum(1 for cell in meaningful[0] if _cell_to_str(cell)) == 1:
        title = _cell_to_str(next(cell for cell in meaningful[0] if _cell_to_str(cell)))
        meaningful = meaningful[1:]
    if len(meaningful) < 2:
        return None

    header = [_cell_to_str(cell) for cell in meaningful[0]]
    body = meaningful[1:]
    if sum(1 for cell in header if cell) < 2:
        return None

    categories: list[str] = []
    columns: dict[int, list[float | None]] = {
        index: [] for index, name in enumerate(header) if index > 0 and name
    }
    for row in body:
        category = _cell_to_str(row[0]) if row else ""
        if not category or category.casefold() in _TOTALS:
            continue
        categories.append(category)
        for index in columns:
            columns[index].append(_cell_to_float(row[index]) if index < len(row) else None)

    series = [
        Series(name=header[index], values=values)
        for index, values in columns.items()
        if any(value is not None for value in values)
    ]
    if len(categories) < 2 or not series:
        return None

    unit_match = _UNIT_IN_TITLE.search(title)
    return Dataset(
        dataset_id=dataset_id,
        title=title,
        categories=categories,
        series=series,
        unit=unit_match.group(1) if unit_match else None,
        source_ref=source_ref,
    )


def _markdown_tables(markdown: str) -> Iterator[list[list[str]]]:
    """Блоки подряд идущих строк, начинающихся с `|`."""
    block: list[list[str]] = []
    for line in markdown.split("\n"):
        if line.lstrip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not all(set(cell) <= set("-: ") for cell in cells):
                block.append(cells)
            continue
        if block:
            yield block
            block = []
    if block:
        yield block


class ContentIngestor:
    """Контент-пакет → `ContentPackage`.

    Порядок обхода файлов детерминирован (сортировка по имени): идентификаторы
    `f001`, `d001`, `a001` обязаны совпадать между прогонами, иначе ссылки в плане
    колоды перестанут указывать туда же при повторной генерации (C11).
    """

    def __init__(self, asset_dir: Path | None = None) -> None:
        #: Куда распаковывать картинки, зашитые в `.docx`. Без него они пропускаются.
        self.asset_dir = asset_dir

    def ingest(self, paths: list[Path], brief: Brief) -> ContentPackage:
        """markitdown → нормализованный markdown → факты, датасеты, ассеты."""
        facts: list[Fact] = []
        datasets: list[Dataset] = []
        assets: list[Asset] = []
        chunks: list[str] = []

        for path in sorted(paths, key=lambda item: item.name):
            suffix = path.suffix.lower()
            if suffix in _IMAGE:
                assets.append(self._image_asset(path, f"a{len(assets) + 1:03d}"))
                continue
            if suffix in _WORKBOOK:
                datasets.extend(self._datasets_from_workbook(path, len(datasets)))
                continue

            markdown = self._markdown_of(path)
            chunks.append(f"<!-- {path.name} -->\n{markdown}")
            facts.extend(self._facts_of(markdown, path.name, len(facts)))
            datasets.extend(self._datasets_from_markdown(markdown, path.name, len(datasets)))
            if suffix == ".docx" and self.asset_dir is not None:
                assets.extend(self._images_from_docx(path, len(assets)))

        return ContentPackage(
            brief=brief,
            facts=facts,
            datasets=datasets,
            assets=assets,
            raw_markdown="\n\n".join(chunks) or None,
        )

    # ------------------------------------------------------------------ чтение

    def _markdown_of(self, path: Path) -> str:
        if not path.exists():
            raise ContentIngestionError(f"файла нет: {path}")
        if path.suffix.lower() in _TEXT_SUFFIXES:
            return _normalize(path.read_text(encoding="utf-8"))
        if path.suffix.lower() not in _CONVERTIBLE:
            raise ContentIngestionError(
                f"формат {path.suffix!r} не поддерживается: {path.name}. "
                "Поддерживаются текст, .docx, .pdf, .pptx, .html и таблицы .xlsx/.csv"
            )

        from markitdown import MarkItDown

        try:
            text = MarkItDown(enable_plugins=False).convert(str(path)).text_content
        except Exception as error:  # причина важнее типа исключения, см. сообщение
            raise ContentIngestionError(
                f"{path.name}: markitdown не смог прочитать файл ({error}). "
                "Чаще всего это значит, что в образе нет конвертера: базовая сборка "
                "markitdown не читает .docx, .pdf, .xlsx и .pptx. "
                "Нужна зависимость markitdown с extras [docx, pdf, xlsx, pptx]"
            ) from error
        if path.suffix.lower() == ".pdf" and sum(ch.isalpha() for ch in text) < _MIN_LETTERS_IN_PDF:
            raise ContentIngestionError(
                f"{path.name}: в PDF нет текстового слоя — похоже на скан. "
                "Пришлите исходник (.docx) или PDF с распознанным текстом"
            )
        return _normalize(text)

    # ------------------------------------------------------------------ факты

    def _facts_of(self, markdown: str, source: str, offset: int) -> list[Fact]:
        facts: list[Fact] = []
        for lineno, line in enumerate(markdown.split("\n"), start=1):
            if line.lstrip().startswith("|") or line.lstrip().startswith("<!--"):
                continue
            text = _plain_text(line)
            if not text:
                continue
            for sentence in _sentences(text):
                if len(sentence.split()) < 3:
                    continue
                facts.append(
                    Fact(
                        fact_id=f"f{offset + len(facts) + 1:03d}",
                        text=sentence,
                        numbers=extract_numbers(sentence),
                        source_ref=f"{source}#L{lineno}",
                    )
                )
        return facts

    # --------------------------------------------------------------- датасеты

    def _datasets_from_workbook(self, path: Path, offset: int) -> list[Dataset]:
        if path.suffix.lower() == ".csv":
            rows = [line.split(",") for line in path.read_text(encoding="utf-8").splitlines()]
            dataset = _dataset_from_rows(
                [list(row) for row in rows], f"d{offset + 1:03d}", path.stem, path.name
            )
            return [dataset] if dataset else []

        # openpyxl без аннотаций; в зависимостях не объявлен — запрос тимлиду в proposal.md
        import openpyxl  # type: ignore[import-untyped]

        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
        datasets: list[Dataset] = []
        for sheet in workbook.worksheets:
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            dataset = _dataset_from_rows(
                rows,
                f"d{offset + len(datasets) + 1:03d}",
                sheet.title,
                f"{path.name}#{sheet.title}",
            )
            if dataset is not None:
                datasets.append(dataset)
        workbook.close()
        return datasets

    def _datasets_from_markdown(self, markdown: str, source: str, offset: int) -> list[Dataset]:
        datasets: list[Dataset] = []
        for table in _markdown_tables(markdown):
            dataset = _dataset_from_rows(
                [list(row) for row in table],
                f"d{offset + len(datasets) + 1:03d}",
                source,
                source,
            )
            if dataset is not None:
                datasets.append(dataset)
        return datasets

    # ----------------------------------------------------------------- ассеты

    def _image_asset(self, path: Path, asset_id: str) -> Asset:
        return Asset(asset_id=asset_id, kind="image", path=str(path), caption=path.stem)

    def _images_from_docx(self, path: Path, offset: int) -> list[Asset]:
        """Картинки лежат в архиве документа, в `word/media/`."""
        if self.asset_dir is None:
            return []
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        assets: list[Asset] = []
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if not name.startswith("word/media/"):
                    continue
                if Path(name).suffix.lower() not in _IMAGE:
                    continue
                target = self.asset_dir / f"{path.stem}_{Path(name).name}"
                target.write_bytes(archive.read(name))
                assets.append(
                    Asset(
                        asset_id=f"a{offset + len(assets) + 1:03d}",
                        kind="image",
                        path=str(target),
                        caption=f"{path.name}: {Path(name).name}",
                    )
                )
        return assets
