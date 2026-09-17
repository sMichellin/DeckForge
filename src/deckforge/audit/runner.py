"""Прогон аудита. Change (15)/(18).

Порядок по ADR-004: сначала детерминированные (дёшево, чинится автоматически),
затем VLM (дорого, чинится через HITL).

Два свойства, ради которых прогон устроен именно так.

**Отчёт воспроизводим.** Проверки идут в порядке `check_id`, находки сортируются
по слайду и идентификатору. Иначе два прогона на одном файле дают отчёты, которые
нельзя сравнить ни глазом, ни тестом.

**Пропуск отличается от прохождения.** Проверка, которой нечего смотреть (нет файла,
нет превью) или которая ещё не реализована соседним change, попадает в `skipped_checks`,
а не растворяется в «нарушений не найдено».

**Реестр наполняет сам прогон.** Проверки заводятся побочным эффектом импорта своего
модуля, и потребитель, который импортировал только `AuditRunner`, получал пустой реестр:
ноль находок, ноль пройденных, ноль пропущенных — отчёт, неотличимый от чистой колоды.
Помнить об этом импорте обязан не каждый вызывающий, а прогон.
"""

from __future__ import annotations

import time
from pathlib import Path

from deckforge.audit import deterministic as _deterministic  # noqa: F401  регистрация
from deckforge.audit import semantic as _semantic  # noqa: F401  регистрация
from deckforge.audit.context import AuditContext
from deckforge.audit.registry import REGISTRY, CheckUnavailable, RegisteredCheck
from deckforge.domain.audit import AuditReport, AuditSummary, Finding
from deckforge.domain.content import ContentPackage
from deckforge.domain.enums import Severity
from deckforge.domain.slide import DeckIR
from deckforge.domain.template import TemplateManifest
from deckforge.registry import load_check_specs


class AuditRunner:
    """Прогон реестра проверок по готовой колоде.

    `enabled_checks` сужает набор до перечисленных id — нужно интерфейсу и тестам;
    выключенные в `configs/audit_checks.yaml` не запускаются в любом случае.
    """

    def __init__(self, enabled_checks: list[str] | None = None) -> None:
        self.enabled_checks = enabled_checks
        self.skipped_checks: list[str] = []

    async def run(
        self,
        deck: DeckIR,
        manifest: TemplateManifest,
        content: ContentPackage,
        previews: dict[str, bytes] | None = None,
        deck_path: Path | None = None,
        vlm: object | None = None,
    ) -> AuditReport:
        started = time.perf_counter()
        specs = {spec.check_id: spec for spec in load_check_specs().checks}
        context = AuditContext(
            manifest=manifest,
            deck=deck,
            content=content,
            previews=previews or {},
            deck_path=deck_path,
            vlm=vlm,
        )

        findings: list[Finding] = []
        skipped: list[str] = []
        passed = 0

        # Порядок из ADR-004: сначала детерминированные — они дёшевы и чинятся
        # автоматически, потом VLM — дорогие и чинятся через человека.
        for registered in [*REGISTRY.deterministic(), *REGISTRY.semantic()]:
            spec = specs.get(registered.check_id)
            if not self._is_enabled(registered, spec):
                skipped.append(registered.check_id)
                continue

            params = dict(spec.params) if spec is not None else {}
            try:
                produced = list(registered.fn(context.with_params(params)))
            except CheckUnavailable:
                # Проверке нечего смотреть: нет файла, превью или внешнего сервиса.
                skipped.append(registered.check_id)
                continue
            except NotImplementedError:
                # Проверка объявлена, но её тело относится к другому change.
                skipped.append(registered.check_id)
                continue

            if produced:
                findings.extend(produced)
            else:
                passed += 1

        self.skipped_checks = skipped
        findings.sort(key=lambda f: (f.slide_id or "", f.check_id, f.finding_id))

        return AuditReport(
            deck_id=deck.deck_id,
            variant=deck.variant,
            findings=findings,
            summary=self._summarize(findings, passed),
            duration_s=round(time.perf_counter() - started, 3),
        )

    def _is_enabled(self, registered: RegisteredCheck, spec: object | None) -> bool:
        if self.enabled_checks is not None and registered.check_id not in self.enabled_checks:
            return False
        return bool(getattr(spec, "enabled", True))

    @staticmethod
    def _summarize(findings: list[Finding], passed: int) -> AuditSummary:
        return AuditSummary(
            errors=sum(1 for f in findings if f.severity is Severity.ERROR),
            warnings=sum(1 for f in findings if f.severity is Severity.WARNING),
            infos=sum(1 for f in findings if f.severity is Severity.INFO),
            passed=passed,
        )
