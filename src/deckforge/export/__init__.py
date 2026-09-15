"""Слой `export`: pptx / pdf / html из одного `DeckIR`. Changes (16), (22).

Контент не пересобирается — три адаптера над одним источником (C4).
"""

from deckforge.export.html import export_html
from deckforge.export.pdf import export_pdf
from deckforge.export.pptx import export_pptx

__all__ = ["export_html", "export_pdf", "export_pptx"]
