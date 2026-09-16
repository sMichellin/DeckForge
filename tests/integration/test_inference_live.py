"""Живые прогоны инференса. Change (8) `inference-client`.

Пропускаются, если не задан ключ: CI не ходит в сеть и не тратит чужую квоту.
Запуск локально:

    DECKFORGE_LLM_API_KEY=hf_... DECKFORGE_LLM_BASE_URL=https://router.huggingface.co/v1 \
    pytest tests/integration/test_inference_live.py -m needs_llm

Проверяется не качество ответов, а контракт: клиент доходит до модели, структурированный
вывод действительно структурирован, картинка доезжает, seed и кэш ведут себя как обещано.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from deckforge.config import get_settings
from deckforge.inference import ResponseCache, client_for, generate_json, generate_model
from deckforge.inference.vlm import VlmJudge

pytestmark = [
    pytest.mark.needs_llm,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("DECKFORGE_LLM_API_KEY", "changeme") == "changeme",
        reason="не задан DECKFORGE_LLM_API_KEY — живой инференс не проверяется",
    ),
]

SCHEMA = {
    "type": "object",
    "properties": {
        "capital": {"type": "string"},
        "population_millions": {"type": "number"},
    },
    "required": ["capital", "population_millions"],
    "additionalProperties": False,
}


class Capital(BaseModel):
    capital: str
    population_millions: float = Field(gt=0)


def test_llm_answers_in_structured_form() -> None:
    client = client_for("llm_main")
    data, completion = generate_json(
        client,
        system="Ты отвечаешь фактами. Ответ строго JSON по схеме.",
        user="Столица Франции и её население в миллионах?",
        response_schema=SCHEMA,
        seed=1,
        max_tokens=3000,
    )
    assert "париж" in data["capital"].lower() or "paris" in data["capital"].lower()
    assert completion.completion_tokens > 0


def test_validated_model_round_trip() -> None:
    result, _ = generate_model(
        client_for("llm_main"),
        Capital,
        system="Ответ строго JSON по схеме.",
        user="Столица Франции и её население в миллионах?",
        response_schema=SCHEMA,
        seed=1,
        max_tokens=3000,
    )
    assert result.population_millions > 0


def test_thinking_model_still_returns_an_answer() -> None:
    """Qwen3.x размышляет, и через роутер это не отключается — бюджет должен добираться сам."""
    completion = client_for("llm_main").complete(
        [{"role": "user", "content": "Ответь одним словом: столица Франции?"}],
        max_tokens=48,
    )
    assert completion.text


def test_vlm_reads_the_schematic_preview(tmp_path: Path) -> None:
    from deckforge.domain.enums import LayoutKind
    from deckforge.parsing.layout_preview import SchematicPreview
    from tests.unit.test_layout_classifier import CONFIDENT, SLIDE

    png = SchematicPreview().render(CONFIDENT, SLIDE.cx_emu, SLIDE.cy_emu)
    judge = VlmJudge(client_for("vlm_judge"), cache=ResponseCache(tmp_path))
    answer = judge.ask_image(
        system="Определи назначение макета. Ответ строго JSON.",
        user="Что это за макет?",
        image_png=png,
        schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": [k.value for k in LayoutKind]},
                "reason": {"type": "string"},
            },
            "required": ["kind", "reason"],
            "additionalProperties": False,
        },
        seed=1,
    )
    assert answer["kind"] in {k.value for k in LayoutKind}


def test_cache_prevents_the_second_call(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    client = client_for("llm_main")
    kwargs = dict(
        system="Ответ строго JSON.",
        user="Столица Франции и её население в миллионах?",
        response_schema=SCHEMA,
        seed=7,
        max_tokens=3000,
        cache=cache,
        skill_ref="live_probe@1.0.0",
    )
    first, c1 = generate_json(client, **kwargs)  # type: ignore[arg-type]
    second, c2 = generate_json(client, **kwargs)  # type: ignore[arg-type]

    assert first == second
    assert c1.from_cache is False and c2.from_cache is True


def test_settings_point_somewhere_real() -> None:
    settings = get_settings()
    assert settings.llm_base_url.startswith("http")
    assert settings.llm_api_key != "changeme"
