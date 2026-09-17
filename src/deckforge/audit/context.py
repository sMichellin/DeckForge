"""Контекст проверки аудита. Change (15) `audit-deterministic`.

Реализация протокола `CheckContext`: всё, что проверке разрешено видеть, и ничего сверх.
Детерминированные проверки пользуются только `manifest`, `deck` и `content` — этого
достаточно, чтобы результат на одном и том же слайде всегда совпадал.

`previews` и `deck_path` нужны проверкам, которым нечего смотреть в IR: файл либо
открывается, либо нет; два слайда либо выглядят одинаково, либо нет. До change (13)
их не существует, поэтому оба поля необязательные, а проверка без них возвращает
пустой список и попадает в список пропущенных — «не запускалась» и «прошла» не одно и то же.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from deckforge.domain.content import ContentPackage
from deckforge.domain.slide import DeckIR
from deckforge.domain.template import TemplateManifest


@dataclass(frozen=True, slots=True)
class AuditContext:
    """Вход любой проверки. Иммутабелен: проверка ничего не меняет, только сообщает."""

    manifest: TemplateManifest
    deck: DeckIR
    content: ContentPackage | None = None
    previews: dict[str, bytes] = field(default_factory=dict)
    deck_path: Path | None = None

    #: Клиент VLM для контекстуальных проверок (change 18). Протокол, а не конкретный
    #: класс: судья тестируется подделкой, без поднятого инференса.
    vlm: Any | None = None

    params: dict[str, Any] = field(default_factory=dict)

    def with_params(self, params: dict[str, Any]) -> AuditContext:
        """Копия с порогами конкретной проверки из `configs/audit_checks.yaml`."""
        return replace(self, params=dict(params))

    def param(self, name: str, default: float) -> float:
        """Числовой порог. Отсутствует в YAML — берётся значение по умолчанию проверки."""
        value = self.params.get(name, default)
        return float(value) if isinstance(value, int | float) else default

    def text_param(self, name: str, default: str) -> str:
        value = self.params.get(name, default)
        return value if isinstance(value, str) else default
