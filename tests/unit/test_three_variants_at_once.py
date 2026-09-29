"""Три варианта из одного шаблона и одних материалов. Change `three-variants-at-once` (план Б).

Один прогон — один вариант (`RunRequest`), поэтому «все варианты» в интерфейсе — это прогон
на каждый вариант с одними и теми же файлами. Файлы человек кладёт один раз.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from frontend.app import ALL_VARIANTS, send, variants_to_run

APP = Path(__file__).resolve().parents[2] / "frontend" / "app.py"
NAMES = {"A": "Плотный аналитический", "B": "Визуальный нарратив", "C": "Executive summary"}


class _File:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


class _Api:
    """Записная книжка вместо сервиса: что создано, что загружено, что запущено."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.variants: list[str] = []

    def create_run(self, **fields: Any) -> str:
        run_id = f"run{len(self.variants) + 1}"
        self.variants.append(str(fields["variant"]))
        self.calls.append(("create", run_id))
        return run_id

    def upload_template(self, run_id: str, name: str, data: bytes) -> None:
        self.calls.append(("template", run_id, name))

    def upload_content(self, run_id: str, name: str, data: bytes) -> None:
        self.calls.append(("content", run_id, name))

    def start(self, run_id: str) -> None:
        self.calls.append(("start", run_id))


SETTINGS = {
    "purpose": "report", "audience": "правление", "slides_mode": "Задать", "target_slides": 12,
    "language": "ru", "seed": 1341, "interactive": False, "profile": "plan_b",
}


def test_all_means_every_named_variant() -> None:
    """Норма: «все сразу» — каждый вариант, что назвал сервис; один выбранный — он один."""
    assert variants_to_run(ALL_VARIANTS, NAMES) == ["A", "B", "C"]
    assert variants_to_run("B", NAMES) == ["B"]


def test_one_template_and_one_text_give_three_runs() -> None:
    """Норма: файлы загружены в каждый прогон, старт — после загрузки, вариант — свой."""
    api = _Api()
    runs = send(
        api,  # type: ignore[arg-type]
        {**SETTINGS, "variant": ALL_VARIANTS},
        _File("шаблон.pptx", b"PK"),
        [_File("текст.md", "# ТЗ".encode())],
        NAMES,
    )

    assert runs == {"A": "run1", "B": "run2", "C": "run3"}
    assert api.variants == ["A", "B", "C"]
    for run_id in runs.values():
        mine = [call for call in api.calls if call[1] == run_id]
        assert mine == [
            ("create", run_id),
            ("template", run_id, "шаблон.pptx"),
            ("content", run_id, "текст.md"),
            ("start", run_id),
        ]


def test_a_single_variant_is_still_one_run() -> None:
    """Нарушитель прежнего вида: выбран один вариант — прогон один, лишних не ставим."""
    api = _Api()
    runs = send(
        api,  # type: ignore[arg-type]
        {**SETTINGS, "variant": "C"},
        _File("шаблон.pptx", b"PK"),
        [_File("текст.md", "# ТЗ".encode())],
        NAMES,
    )

    assert runs == {"C": "run1"}
    assert [call[0] for call in api.calls].count("start") == 1


def test_the_page_offers_all_variants_at_once() -> None:
    """Норма: в переключателе есть пункт «все сразу», страница без сервиса не падает."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(APP), default_timeout=30)
    app.run()

    assert not app.exception
    radio = next(item for item in app.radio if item.label == "Вариант вёрстки")
    assert list(radio.options)[-1].startswith("Все")
