"""Превью слайда-примера шаблона для листа колоды. Change `the-deck-sheet`, план Б, шаг 6.

Рендер кладёт превью примеров в кэш шаблона один раз (`pipeline/nodes/render.py`,
`EXAMPLES_DIR`): `<кэш>/example-previews/<template_id>/<имя>-NN.png`, страницы в порядке
PDF. Сервис их только читает — без модели, без рендера и без python-pptx.

**Страница — не номер примера.** `recipe_id` = `ex<номер части slideN.xml>`, а PDF идёт
в порядке показа (`sldIdLst`) и без скрытых слайдов. На шаблонах кейса они совпадают, на
незнакомом не обязаны, поэтому порядок читается из `presentation.xml` шаблона прогона.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree

from deckforge.parsing.template import template_id_of
from deckforge.pipeline.nodes.render import EXAMPLES_DIR

#: Кэш шаблонов внутри каталога артефактов — тот же, что у графа (`api/jobs.py`).
TEMPLATE_CACHE_DIR = "template-cache"

_RECIPE_ID = re.compile(r"^ex(\d{1,4})$")
_PAGE = re.compile(r"-(\d+)\.png$")
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def example_number(recipe_id: str) -> int | None:
    """Номер части слайда-примера по `recipe_id`; не вида `ex<номер>` — `None`."""
    match = _RECIPE_ID.match(recipe_id)
    return int(match.group(1)) if match else None


def shown_slide_parts(template: Path) -> list[str]:
    """Части слайдов в порядке показа, без скрытых: `ppt/slides/slideN.xml`."""
    return list(_shown_slide_parts(str(template), *_stamp(template)))


def _stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=16)
def _shown_slide_parts(template: str, _mtime: int, _size: int) -> tuple[str, ...]:
    with zipfile.ZipFile(template) as package:
        presentation = ElementTree.fromstring(package.read("ppt/presentation.xml"))
        rels = ElementTree.fromstring(package.read("ppt/_rels/presentation.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target", "") for rel in rels.iter(f"{_REL}Relationship")}
        shown: list[str] = []
        for slide_id in presentation.iter(f"{_P}sldId"):
            target = targets.get(slide_id.get(f"{_R}id"))
            if not target:
                continue
            part = posixpath.normpath(posixpath.join("ppt", target)).lstrip("/")
            if part in package.namelist() and not _hidden(package.read(part)):
                shown.append(part)
    return tuple(shown)


def _hidden(slide_xml: bytes) -> bool:
    """`<p:sld show="0">` — слайд скрыт, и в PDF его страницы нет."""
    root = ElementTree.fromstring(slide_xml)
    return root.get("show") in ("0", "false")


@lru_cache(maxsize=16)
def _template_id(template: str, _mtime: int, _size: int) -> str:
    return template_id_of(Path(template))


def example_preview(template: Path, recipe_id: str, cache_root: Path) -> Path | None:
    """Файл превью слайда-примера или `None`: нет шаблона, кэша, примера или страницы."""
    number = example_number(recipe_id)
    if number is None or not template.is_file():
        return None
    part = f"ppt/slides/slide{number}.xml"
    shown = shown_slide_parts(template)
    if part not in shown:
        return None
    page = shown.index(part) + 1

    folder = (cache_root / EXAMPLES_DIR / _template_id(str(template), *_stamp(template)).replace(
        ":", "_"
    )).resolve()
    if not folder.is_dir() or cache_root.resolve() not in folder.parents:
        return None
    for candidate in folder.glob("*.png"):
        found = _PAGE.search(candidate.name)
        if found and int(found.group(1)) == page:
            return candidate
    return None
