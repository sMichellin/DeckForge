"""Чекпойнт знает свои типы. Change `the-checkpoint-knows-its-types` (план Б, тимлид).

LangGraph восстанавливает из чекпойнта только названные типы (msgpack-allowlist): неназванные
пока идут с предупреждением на каждом, а в строгом режиме (`LANGGRAPH_STRICT_MSGPACK`) —
не восстанавливаются. Снимки прогонов (`pipeline/replay.py`, `deckforge audit`) на этом
держатся целиком: без списка они перестали бы читаться с очередным обновлением LangGraph.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from deckforge.composition.assign import RecipeAssignment
from deckforge.designsystem.models import PlaceKind, RecipeKind
from deckforge.domain.enums import LayoutKind, Severity
from deckforge.domain.slide import DeckIR
from deckforge.domain.template import TemplateManifest
from deckforge.pipeline.replay import from_fixture
from deckforge.pipeline.run import checkpoint_types, open_checkpointer

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "2026-09-29" / "vk-tech"


def test_the_list_covers_the_domain_the_design_system_and_the_assignments() -> None:
    """Норма: в списке модели и перечисления всех трёх мест, откуда тип попадает в состояние."""
    types = set(checkpoint_types())

    assert {DeckIR, TemplateManifest, LayoutKind, Severity, RecipeKind, PlaceKind,
            RecipeAssignment} <= types


def test_a_new_domain_model_needs_no_registration() -> None:
    """Норма: список собирается обходом модулей — каждая модель `domain` в нём есть."""
    from pydantic import BaseModel

    import deckforge.domain.content as content

    declared = {
        value for value in vars(content).values()
        if isinstance(value, type) and issubclass(value, BaseModel)
        and value.__module__ == content.__name__
    }

    assert declared <= set(checkpoint_types())


_STRICT = """
from pathlib import Path
from deckforge.pipeline.run import checkpoint_serde
from deckforge.pipeline.replay import from_fixture
from deckforge.composition.assign import RecipeAssignment
snapshot = from_fixture(Path({fixture!r}))
serde = checkpoint_serde()
values = [snapshot.deck, snapshot.manifest,
          RecipeAssignment(slide_id="s01", recipe_id=None, reason="примера нет")]
print(all(serde.loads_typed(serde.dumps_typed(v)) == v for v in values))
"""


def test_a_snapshot_survives_strict_deserialization() -> None:
    """Нарушитель без правки: в строгом режиме штатный сериализатор возвращает вместо колоды
    `dict`. Со списком типов IR колоды, манифест и назначения 29.09 возвращаются моделями.

    Отдельный процесс: LangGraph читает `LANGGRAPH_STRICT_MSGPACK` при импорте.
    """
    code = _STRICT.format(fixture=str(FIXTURE))
    env = {**os.environ, "LANGGRAPH_STRICT_MSGPACK": "true"}

    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                          text=True, check=True)

    assert done.stdout.strip().splitlines()[-1] == "True", done.stderr


def test_reading_a_checkpoint_warns_about_no_type(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Нарушитель без правки: чтение чекпойнта с IR колоды не предупреждает ни об одном типе."""
    snapshot = from_fixture(FIXTURE)

    async def roundtrip() -> DeckIR:
        async with open_checkpointer(tmp_path / "c.sqlite") as saver:
            await saver.setup()
            raw = saver.serde.dumps_typed(snapshot.deck)
            back: DeckIR = saver.serde.loads_typed(raw)
            return back

    with caplog.at_level(logging.WARNING):
        back = asyncio.run(roundtrip())

    assert back == snapshot.deck
    assert not [r for r in caplog.records if "unregistered type" in r.getMessage()]
