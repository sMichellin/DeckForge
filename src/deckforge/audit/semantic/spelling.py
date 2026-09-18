"""`content.no_typos` — LanguageTool, а не модель: орфография детерминируема (§5.2).

Проверка живёт в `semantic/`, но объявлена детерминированной, и это не противоречие:
папка отвечает на вопрос «про смысл ли проверка», а флаг — «одинаков ли результат
на повторных запусках». Опечатка либо есть, либо нет; спрашивать об этом VLM значит
получать разные ответы на одном тексте.

LanguageTool — внешний сервис (`DECKFORGE_LANGUAGETOOL_URL`). Его может не быть:
в CI он не поднимается, на машине разработчика тоже. Тогда проверка поднимает
`CheckUnavailable`, и прогон пишет её в пропущенные — «не проверяли» и «опечаток нет»
разные состояния, а пустой список означал бы второе.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from deckforge.audit.findings import make_finding
from deckforge.audit.geometry import block_bbox, block_text, layout_of
from deckforge.audit.registry import CheckContext, CheckUnavailable, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import Severity


@dataclass(frozen=True, slots=True)
class Typo:
    """Одна находка LanguageTool, приведённая к тому, что нужно аудиту."""

    message: str
    offset: int
    length: int
    rule_id: str
    replacements: tuple[str, ...] = ()

    @property
    def fragment_hint(self) -> str:
        return f"{self.offset}:{self.length}"


class SpellChecker(Protocol):
    """Узкий интерфейс вместо самой библиотеки: так проверка тестируется подделкой."""

    def check(self, text: str) -> Sequence[Typo]: ...


def _language_tool(language: str, url: str | None) -> SpellChecker | None:
    """Клиент LanguageTool или `None`, если библиотеки либо сервера нет.

    Импорт внутри функции намеренно: `language_tool_python` при импорте не требует сети,
    но создание клиента требует, и падение не должно ронять весь реестр проверок.
    """
    try:
        import language_tool_python
    except ImportError:
        return None

    try:
        # `LanguageTool`, а не `LanguageToolPublicAPI`: последний сам подставляет адрес
        # публичного сервиса languagetool.org, и второй `remote_server` роняет его
        # с `TypeError: got multiple values for keyword argument`. Фабрика глотала это
        # исключение, и проверка ни разу не работала ни в одном окружении (замер 18.09).
        # Тесты подменяют фабрику целиком, поэтому настоящий клиент в них не создавался.
        tool: Any = language_tool_python.LanguageTool(language, remote_server=url or None)
    except Exception:
        return None

    return _LanguageToolAdapter(tool)


@dataclass(frozen=True, slots=True)
class _LanguageToolAdapter:
    tool: Any

    def check(self, text: str) -> Sequence[Typo]:
        return [
            Typo(
                message=match.message,
                offset=match.offset,
                length=match.errorLength,
                rule_id=match.ruleId,
                replacements=tuple(match.replacements[:3]),
            )
            for match in self.tool.check(text)
        ]


#: Подменяется в тестах: поднимать LanguageTool ради проверки текста незачем.
checker_factory: Callable[[str, str | None], SpellChecker | None] = _language_tool


@check(id="content.no_typos", deterministic=True, severity=Severity.WARNING,
       title="Текст без опечаток")
def no_typos(ctx: CheckContext) -> Iterable[Finding]:
    """Текст без опечаток."""
    language = getattr(ctx.deck, "language", None) or "ru"
    url = ctx.text_param("server_url", "")
    checker = checker_factory(language, url or None)
    if checker is None:
        # Сервиса нет — проверка не запускалась. Молчаливое «всё хорошо» было бы враньём.
        raise CheckUnavailable("LanguageTool недоступен: нет библиотеки или сервера")

    for slide in ctx.deck.slides:
        layout = layout_of(slide, ctx.manifest)
        for block in slide.blocks:
            text = block_text(block).strip()
            if not text:
                continue
            for typo in checker.check(text):
                fragment = text[typo.offset : typo.offset + typo.length]
                suggestion = (
                    f"; возможно: {', '.join(typo.replacements)}" if typo.replacements else ""
                )
                yield make_finding(
                    check_id="content.no_typos",
                    slide_id=slide.slide_id,
                    block_id=block.block_id,
                    bbox=block_bbox(block, layout),
                    reason=f"typo:{typo.rule_id}:{typo.fragment_hint}",
                    message=f"«{fragment}» — {typo.message}{suggestion}",
                    evidence={
                        "rule_id": typo.rule_id,
                        "fragment": fragment,
                        "language": language,
                    },
                )
