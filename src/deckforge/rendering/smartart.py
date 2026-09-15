"""Составные компоненты вместо OOXML SmartArt. Change (21) `smartart-icons`.

python-pptx не создаёт diagram-part, а инъекция готового XML даёт нередактируемый объект.
Собираем из автофигур и коннекторов: каждый элемент — отдельная редактируемая фигура,
что выполняет C3 строже, чем настоящий SmartArt (§10).
"""

from __future__ import annotations

from deckforge.domain.slide import SmartArtBlock
from deckforge.domain.template import TemplateManifest


def add_smartart(slide: object, block: SmartArtBlock, manifest: TemplateManifest) -> list[object]:
    raise NotImplementedError("change (21) smartart-icons")
