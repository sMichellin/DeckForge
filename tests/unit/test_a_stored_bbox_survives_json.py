"""Хранимый `BBox` переживает круг через JSON. Change `red-tests-on-main`.

`right` и `bottom` — вычисляемые поля: pydantic пишет их в JSON, а `extra="forbid"`
отвергал их при чтении. Падал манифест с декором (`StaticShape.bbox`) — на `main`
это был `test_manifest_round_trips_through_json[Metropolis.pptx]`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deckforge.domain.base import BBox
from deckforge.domain.template import StaticShape


def test_a_bbox_survives_json() -> None:
    box = BBox(x=10, y=20, cx=300, cy=400)

    dumped = box.model_dump_json()

    assert '"right":310' in dumped
    assert BBox.model_validate_json(dumped) == box


def test_a_static_shape_survives_json() -> None:
    """Нарушитель до правки: декор шаблона не читался обратно."""
    shape = StaticShape(shape_id="sp7", bbox=BBox(x=0, y=0, cx=10080000, cy=5670000), z=3)

    assert StaticShape.model_validate_json(shape.model_dump_json()) == shape


def test_other_extra_fields_are_still_forbidden() -> None:
    """Норма: снимаются только вычисляемые поля, строгость модели прежняя."""
    with pytest.raises(ValidationError):
        BBox.model_validate({"x": 0, "y": 0, "cx": 1, "cy": 1, "width": 1})
