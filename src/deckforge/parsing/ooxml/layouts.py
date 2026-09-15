"""Плейсхолдеры с каскадом slideMaster → slideLayout. Change (3) `template-parsing-core`."""

from __future__ import annotations

from deckforge.domain.template import PlaceholderSpec


def resolve_placeholders(layout_xml: bytes, master_xml: bytes) -> list[PlaceholderSpec]:
    """Наследование геометрии и типа: значение из макета перекрывает значение мастера."""
    raise NotImplementedError("change (3) template-parsing-core")
