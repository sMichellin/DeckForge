"""Хранилище прогонов на файловой системе. Change (23) `service-api`.

**Почему файлы, а не Redis.** Через очередь ходит одно короткое сообщение — «начни этот
прогон». Всё остальное — загруженный шаблон, превью, экспорт, чекпойнт — это файлы,
которые всё равно лежат на диске, и класть их копию в Redis значило бы завести второй
источник истины. Каталог прогона монтируется и в приложение, и в воркер
(`docker/compose.yaml`), поэтому статус, написанный воркером, читается приложением
без посредника.

Побочная выгода важнее экономии: после падения Redis прогон остаётся на диске целиком —
с отчётом, превью и файлами. Разбирать его можно руками, а не по логам.

Раскладка одного прогона::

    artifacts/runs/<run_id>/
        in/template.pptx        загруженный шаблон
        in/content/…            загруженные материалы
        status.json             стадия, прогресс, ошибка — пишет воркер
        request.json            чем прогон запрошен: вариант, seed, бриф
        checkpoint.sqlite       чекпойнт графа, без него нет HITL
        out/…                   previews/, run.json, экспорт
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Стадии графа в порядке прохождения — по ним считается прогресс. Список свой,
#: а не импортированный из `pipeline.budget`: транспорт показывает пользователю
#: путь колоды, и менять этот путь из-за правки бюджета неправильно.
STAGES: tuple[str, ...] = (
    "parse_template",
    "ingest_content",
    "plan",
    "compose",
    "fit",
    "render",
    "audit",
    "export",
)

#: Прогон, который закончился. Остальные состояния означают, что ждать есть чего.
FINAL_STATES = frozenset({"done", "failed"})


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class RunPaths:
    """Пути одного прогона. Ни один из них не собирается по строке в другом месте."""

    root: Path

    @property
    def inputs(self) -> Path:
        return self.root / "in"

    @property
    def content(self) -> Path:
        return self.inputs / "content"

    @property
    def template(self) -> Path:
        # Расширение хранится в `request.json`: имя файла пользователя в путь не идёт,
        # иначе загрузка «../../etc/passwd.pptx» выбирала бы, куда писать.
        return next(iter(sorted(self.inputs.glob("template.*"))), self.inputs / "template.pptx")

    @property
    def status_file(self) -> Path:
        return self.root / "status.json"

    @property
    def request_file(self) -> Path:
        return self.root / "request.json"

    @property
    def checkpoint(self) -> Path:
        return self.root / "checkpoint.sqlite"

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def previews(self) -> Path:
        return self.out / "previews"

    @property
    def previews_index(self) -> Path:
        """`slide_id` → имя файла превью.

        Без него превью не найти: рендер именует страницы `deck-1.png`, `deck-2.png`,
        а аудит и находки оперируют `slide_id` — после `split_slide` номера страниц
        и слайды расходятся (`audit/preview.py`).
        """
        return self.out / "previews.json"

    @property
    def report_file(self) -> Path:
        return self.out / "run.json"


@dataclass(slots=True)
class RunStore:
    """Каталог прогонов. Единственное место, которое знает раскладку файлов."""

    root: Path
    _ids: set[str] = field(default_factory=set)

    def paths(self, run_id: str) -> RunPaths:
        return RunPaths(self.root / self.safe_id(run_id))

    def exists(self, run_id: str) -> bool:
        return (self.root / self.safe_id(run_id)).is_dir()

    def create(self, *, request: dict[str, Any]) -> str:
        run_id = uuid.uuid4().hex[:12]
        paths = self.paths(run_id)
        paths.content.mkdir(parents=True, exist_ok=True)
        paths.out.mkdir(parents=True, exist_ok=True)
        _write_json(paths.request_file, {"run_id": run_id, "created_at": utcnow(), **request})
        self.write_status(run_id, state="queued", stage=None)
        return run_id

    def save_template(self, run_id: str, name: str, data: bytes) -> Path:
        suffix = Path(name).suffix.lower() or ".pptx"
        target = self.paths(run_id).inputs / f"template{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def save_content(self, run_id: str, name: str, data: bytes) -> Path:
        # Имя файла пользователя — данные, а не путь: берётся только его базовая часть.
        target = self.paths(run_id).content / Path(name).name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def request(self, run_id: str) -> dict[str, Any]:
        return _read_json(self.paths(run_id).request_file)

    def status(self, run_id: str) -> dict[str, Any]:
        return _read_json(self.paths(run_id).status_file)

    def report(self, run_id: str) -> dict[str, Any] | None:
        path = self.paths(run_id).report_file
        return _read_json(path) if path.exists() else None

    def save_previews(self, run_id: str, previews: dict[str, Path]) -> None:
        """Запоминает, какой файл какому слайду принадлежит. Хранится имя, не путь.

        Путь уехал бы вместе с каталогом прогона при переносе на другую машину,
        а имя привязано к `previews/` и переживает перенос.
        """
        paths = self.paths(run_id)
        _write_json(
            paths.previews_index,
            {slide_id: Path(path).name for slide_id, path in previews.items()},
        )

    def preview_of(self, run_id: str, slide_id: str) -> Path | None:
        """Файл превью слайда или `None`.

        Имя берётся из указателя, а не собирается из `slide_id`, который приходит
        из URL. И всё же результат проверяется на принадлежность каталогу: указатель
        пишем мы, но одного доверия мало, когда на другом конце путь файловой системы.
        """
        paths = self.paths(run_id)
        if not paths.previews_index.exists():
            return None
        name = _read_json(paths.previews_index).get(slide_id)
        if not isinstance(name, str) or not name:
            return None
        candidate = (paths.previews / name).resolve()
        if paths.previews.resolve() not in candidate.parents or not candidate.is_file():
            return None
        return candidate

    def write_status(
        self,
        run_id: str,
        *,
        state: str,
        stage: str | None,
        elapsed_s: float = 0.0,
        error: str | None = None,
        degradations: list[str] | None = None,
        findings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Статус переписывается целиком: частичное обновление дало бы несогласованный вид.

        `findings` не пусты только в состоянии `waiting_choice` — это те находки,
        на ответ по которым граф остановлен.

        `degradations` и `error` — разные вещи, и у них разные поля. Деградация значит,
        что колода собрана более дешёвым путём (§15); ошибка — что что-то не отработало.
        Пока они лежали вместе, удачный прогон показывал в интерфейсе текст в поле
        ошибки, и это выглядело как сбой.
        """
        payload = {
            "run_id": run_id,
            "state": state,
            "stage": stage,
            "progress": progress_of(stage, state),
            "elapsed_s": round(elapsed_s, 3),
            "error": error,
            "degradations": degradations or [],
            "findings": findings or [],
            "updated_at": utcnow(),
        }
        _write_json(self.paths(run_id).status_file, payload)
        return payload

    def delete(self, run_id: str) -> None:
        shutil.rmtree(self.root / self.safe_id(run_id), ignore_errors=True)

    @staticmethod
    def safe_id(run_id: str) -> str:
        """`run_id` приходит из URL и идёт в путь — значит, проверяется, а не чистится.

        Чистка («выкинем точки и слэши») всегда что-нибудь пропускает. Идентификатор
        выдаём мы сами: шестнадцатеричные символы и ничего больше.
        """
        value = run_id.strip()
        if not value or len(value) > 64 or not all(c in "0123456789abcdef" for c in value):
            raise ValueError(f"недопустимый run_id: {run_id!r}")
        return value


def progress_of(stage: str | None, state: str) -> float:
    """Доля пройденных стадий. Ни одной догадки о том, сколько осталось внутри стадии.

    Виток починки возвращает граф на `fit`, и прогресс при этом откатывается назад.
    Это честнее, чем монотонная полоска: колода действительно пересобирается заново.
    """
    if state == "done":
        return 1.0
    if stage is None or stage not in STAGES:
        return 0.0
    return round((STAGES.index(stage) + 1) / len(STAGES), 3)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))
