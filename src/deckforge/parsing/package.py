"""Доступ к .pptx/.potx как к OPC-пакету. Change (3) `template-parsing-core`.

Пакет читается напрямую zip + lxml, а не через python-pptx (ADR-008): парсинг не должен
зависеть от библиотеки записи, а связи между частями нужны целиком — python-pptx отдаёт
не всё (тему, viewProps, порядок мастеров).
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = OFFICE_REL

REL_MASTER = f"{OFFICE_REL}/slideMaster"
REL_LAYOUT = f"{OFFICE_REL}/slideLayout"
REL_THEME = f"{OFFICE_REL}/theme"
REL_IMAGE = f"{OFFICE_REL}/image"


@dataclass(frozen=True, slots=True)
class Relationship:
    rel_id: str
    rel_type: str
    target: str


class NotATemplateError(ValueError):
    """Файл не является пакетом презентации.

    Отдельный тип нужен, чтобы вызывающий код не ловил `zipfile.BadZipFile`:
    внутреннее устройство хранилища — не его дело.
    """


class TemplatePackage:
    """Открытый пакет шаблона. Закрывается через контекстный менеджер."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self._zip = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise NotATemplateError(f"{path.name}: файл не открывается как .pptx/.potx") from exc
        self._names = set(self._zip.namelist())

        if self.presentation_part not in self._names:
            self._zip.close()
            raise NotATemplateError(f"{path.name}: в пакете нет ppt/presentation.xml")

    def __enter__(self) -> TemplatePackage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._zip.close()

    def has(self, part: str) -> bool:
        return part in self._names

    def read(self, part: str) -> bytes:
        return self._zip.read(part)

    def read_optional(self, part: str) -> bytes | None:
        return self._zip.read(part) if part in self._names else None

    def rels_of(self, part: str) -> dict[str, Relationship]:
        """Связи части. Пути разрешаются относительно каталога самой части."""
        directory, name = posixpath.split(part)
        rels_part = posixpath.join(directory, "_rels", f"{name}.rels")
        raw = self.read_optional(rels_part)
        if raw is None:
            return {}

        root = etree.fromstring(raw)
        out: dict[str, Relationship] = {}
        for node in root.iter(f"{{{PKG_REL}}}Relationship"):
            rel_id = node.get("Id")
            target = node.get("Target") or ""
            if not rel_id or node.get("TargetMode") == "External":
                continue
            resolved = posixpath.normpath(posixpath.join(directory, target))
            out[rel_id] = Relationship(rel_id, node.get("Type") or "", resolved)
        return out

    def related(self, part: str, rel_type: str) -> list[str]:
        return [rel.target for rel in self.rels_of(part).values() if rel.rel_type == rel_type]

    @property
    def presentation_part(self) -> str:
        return "ppt/presentation.xml"

    def master_parts(self) -> list[str]:
        """Мастера в том порядке, в котором их объявляет презентация.

        Порядок важен: первый мастер задаёт тему всей колоды, и манифест берёт палитру
        именно у него.
        """
        rels = self.rels_of(self.presentation_part)
        root = etree.fromstring(self.read(self.presentation_part))
        ordered: list[str] = []
        for node in root.iter(f"{{{P}}}sldMasterId"):
            rel_id = node.get(f"{{{R}}}id")
            rel = rels.get(rel_id or "")
            if rel and rel.rel_type == REL_MASTER:
                ordered.append(rel.target)
        if ordered:
            return ordered
        pattern = re.compile(r"ppt/slideMasters/slideMaster\d+\.xml")
        return sorted(n for n in self._names if pattern.fullmatch(n))

    def layout_parts(self, master_part: str) -> list[str]:
        return self.related(master_part, REL_LAYOUT)

    def theme_part(self, master_part: str) -> str | None:
        themes = self.related(master_part, REL_THEME)
        return themes[0] if themes else None

    def media_of(self, part: str) -> tuple[dict[str, bytes], dict[str, str]]:
        """Картинки, на которые ссылается часть: содержимое по имени части и rId → часть."""
        targets = {
            rel.rel_id: rel.target
            for rel in self.rels_of(part).values()
            if rel.rel_type == REL_IMAGE
        }
        blobs = {
            target: self.read(target) for target in set(targets.values()) if self.has(target)
        }
        return blobs, targets

    def slide_size(self) -> tuple[int, int]:
        root = etree.fromstring(self.read(self.presentation_part))
        node = root.find(f"{{{P}}}sldSz")
        if node is None:
            raise ValueError("в presentation.xml нет sldSz: это не презентация")
        return int(node.get("cx")), int(node.get("cy"))

    def layout_name(self, layout_part: str) -> str:
        root = etree.fromstring(self.read(layout_part))
        node = root.find(f"{{{P}}}cSld")
        return (node.get("name") if node is not None else None) or posixpath.basename(layout_part)
