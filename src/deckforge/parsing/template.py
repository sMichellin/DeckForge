"""pptx/potx → `TemplateManifest`. Change (3) `template-parsing-core`.

Кэш по SHA-256 файла: повторный парсинг того же шаблона — 0 с (§12).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from deckforge.domain.template import TemplateManifest

PARSER_VERSION = "1.0.0"


def template_id_of(path: Path) -> str:
    """`sha256:<hex>` — идентификатор шаблона и ключ кэша манифеста."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


class TemplateParser:
    """Единственная точка, где читается исходный .pptx-шаблон (ADR-003)."""

    def __init__(self, cache_dir: Path | None = None, classify_layouts: bool = True) -> None:
        self.cache_dir = cache_dir
        self.classify_layouts = classify_layouts

    def parse(self, path: Path) -> TemplateManifest:
        """Собрать манифест: размер, тема, типошкала, сетка, макеты, декор.

        Порядок: `ooxml.theme` → `ooxml.layouts` (каскад master→layout) →
        `typography.derive_scale` → `ooxml.guides` (или вывод кластеризацией) →
        `layout_kind.classify` → `capacity.compute`.
        """
        raise NotImplementedError("change (3) template-parsing-core")

    def load_cached(self, template_id: str) -> TemplateManifest | None:
        raise NotImplementedError("change (3) template-parsing-core")
