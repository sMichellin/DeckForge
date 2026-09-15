"""VLM-вызовы: классификация макетов и аудит-судья. Change (5)/(18)."""

from __future__ import annotations

from deckforge.inference.client import InferenceClient


async def ask_image(
    client: InferenceClient, system: str, user: str, image_png: bytes, *, seed: int
) -> str:
    raise NotImplementedError("change (8) inference-client")
