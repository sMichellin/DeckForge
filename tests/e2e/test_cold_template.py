"""C6: колода собирается на шаблоне, который не использовался при разработке.

Фикстура `tests/fixtures/templates/cold/` пополняется только тем, что команда не открывала
при написании парсера. Правило PLAN.md §8: любая правка парсера или композитора
проверяется на холодном шаблоне.
"""

from __future__ import annotations

import pytest


@pytest.mark.cold
@pytest.mark.slow
@pytest.mark.skip(reason="change (16) export-pptx-pdf, гейт 20.09")
def test_cold_template_end_to_end() -> None:
    raise NotImplementedError
