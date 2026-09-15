"""Text-to-image ≤ 20B. Change (24) `image-generation` — задача «со звёздочкой».

Цепочка деградации: сгенерированное изображение → иконка из библиотеки → без изображения (§15).
"""

from __future__ import annotations

from deckforge.inference.client import InferenceClient


async def generate_image(
    client: InferenceClient, prompt: str, *, width: int, height: int, seed: int
) -> bytes:
    raise NotImplementedError("change (24) image-generation")
