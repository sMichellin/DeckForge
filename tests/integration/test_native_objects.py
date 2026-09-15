"""C3: ни один слайд не является единым растровым изображением. Change (13)/(16)."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="change (13) pptx-writer")
def test_every_slide_has_editable_objects() -> None:
    raise NotImplementedError
