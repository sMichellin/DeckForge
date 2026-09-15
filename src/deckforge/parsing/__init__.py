"""Слой `parsing`: .pptx/.potx → `TemplateManifest`, контент-пакет → `ContentPackage`.

Changes: (3) template-parsing-core, (4) theme-extraction, (5) layout-classification,
(6) template-preview-render, (7) content-ingestion.
"""

from deckforge.parsing.content import ContentIngestor
from deckforge.parsing.package import TemplatePackage
from deckforge.parsing.template import PARSER_VERSION, TemplateParser, template_id_of

__all__ = [
    "PARSER_VERSION",
    "ContentIngestor",
    "TemplatePackage",
    "TemplateParser",
    "template_id_of",
]
