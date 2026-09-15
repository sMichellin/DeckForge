"""Одиннадцать вопросов Приложения 1 ТЗ как отдельные `content.*` проверки.

Change (18) `audit-semantic`. Формат ответа строго `{"verdict": "yes"|"no", "reason": "…"}`
через constrained decoding; снижение дисперсии — 3 прогона с разными seed и мажоритарное
голосование (ARCHITECTURE.md §5.2).

Из одиннадцати вопросов два здесь не живут:
* «все цифры есть в исходных материалах» — `semantic/grounding.py`, там сверка детерминированная;
* «текст без опечаток» — `semantic/spelling.py`, это LanguageTool, а не модель.
"""

from __future__ import annotations

from collections.abc import Iterable

from deckforge.audit.registry import CheckContext, check
from deckforge.domain.audit import Finding
from deckforge.domain.enums import AutoFix, Severity

QUESTIONS: dict[str, str] = {
    "content.headline_is_conclusion": "Заголовок содержит вывод, а не просто называет тему?",
    "content.body_matches_headline": "Содержимое слайда соответствует заголовку?",
    "content.one_sentence_summary": "Слайд пересказывается одним предложением?",
    "content.has_substance": "На слайде есть содержание, а не только заголовок?",
    "content.visuals_on_topic": "Картинки и иконки относятся к теме слайда?",
    "content.no_prompt_leftovers": "Нет служебного мусора: реплик спикера, кусков промпта?",
    "content.single_language": "Вся колода на одном языке?",
    "content.table_rows_meaningful": "Все строки таблицы и элементы легенды работают на мысль?",
    "content.neighbours_connected": "Соседние слайды связаны между собой по логике?",
}

# Тяжесть и авто-фикс синхронизированы с `configs/audit_checks.yaml`
# (расхождение ловит tests/unit/test_audit_registry.py).
_SEVERITY: dict[str, Severity] = {
    "content.headline_is_conclusion": Severity.WARNING,
    "content.body_matches_headline": Severity.WARNING,
    "content.one_sentence_summary": Severity.INFO,
    "content.has_substance": Severity.WARNING,
    "content.visuals_on_topic": Severity.WARNING,
    "content.no_prompt_leftovers": Severity.ERROR,
    "content.single_language": Severity.WARNING,
    "content.table_rows_meaningful": Severity.INFO,
    "content.neighbours_connected": Severity.INFO,
}
_AUTO_FIX: dict[str, AutoFix] = {
    "content.headline_is_conclusion": AutoFix.REGENERATE_HEADLINE,
}


def _make_check(check_id: str, question: str) -> None:
    """Регистрирует проверку-вопрос. Отдельных функций не пишем: они отличались бы
    только строкой вопроса, а расхождение между ними — источник ошибок."""

    @check(
        id=check_id,
        deterministic=False,
        severity=_SEVERITY[check_id],
        auto_fix=_AUTO_FIX.get(check_id, AutoFix.NONE),
        title=question,
    )
    def _check(ctx: CheckContext) -> Iterable[Finding]:
        raise NotImplementedError("change (18) audit-semantic")


for _check_id, _question in QUESTIONS.items():
    _make_check(_check_id, _question)


async def ask(check_id: str, preview_png: bytes, votes: int = 3) -> tuple[bool, float, str]:
    """Мажоритарное голосование по `votes` прогонам с разными seed.

    Возвращает (вердикт, уверенность, причина). Уверенность ниже порога из конфига
    означает, что проверка промолчала, а не что слайд хорош.
    """
    raise NotImplementedError("change (18) audit-semantic")
