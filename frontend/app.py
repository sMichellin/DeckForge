"""Интерфейс DeckForge на Streamlit. Change (23) `web-ui`.

Весь путь мышью: загрузка шаблона и материалов → прогресс по стадиям → превью слайдов →
находки с подсветкой прямо на слайде → выбор, что исправить → повторная проверка →
скачивание в трёх форматах.

Логики здесь нет: разговор с сервисом живёт в `client.py`, рисование рамок — в
`highlight.py`, и обе проверены тестами. В этом файле только разметка и переходы,
потому что их проверить можно лишь глазами.

Запуск: `streamlit run frontend/app.py` (в `docker/compose.yaml` — сервис `ui`).
"""

from __future__ import annotations

import os
import time
from typing import Any

import streamlit as st

from frontend.client import DEFAULT_BASE_URL, DeckForgeClient, ServiceError
from frontend.highlight import by_slide, draw_findings

#: Как часто перерисовывать страницу, пока прогон идёт. Стадии длятся десятки секунд —
#: чаще раза в секунду обновлять нечего.
REFRESH_S = 1.0

STATE_LABELS: dict[str, str] = {
    "queued": "в очереди",
    "running": "идёт",
    "waiting_choice": "ждёт вашего решения",
    "done": "готово",
    "failed": "не получилось",
}
EXPORT_LABELS: dict[str, str] = {"pptx": "PowerPoint", "pdf": "PDF", "html": "HTML"}


def client() -> DeckForgeClient:
    base = st.session_state.get("base_url") or os.environ.get(
        "DECKFORGE_API_URL", DEFAULT_BASE_URL
    )
    if st.session_state.get("_client_base") != base:
        st.session_state["_client"] = DeckForgeClient(base_url=str(base))
        st.session_state["_client_base"] = base
    return st.session_state["_client"]  # type: ignore[no-any-return]


def main() -> None:
    st.set_page_config(page_title="DeckForge", page_icon="🗂", layout="wide")
    st.title("DeckForge")
    st.caption("Презентация в стиле вашего шаблона — из ваших материалов")

    with st.sidebar:
        settings = sidebar()

    run_id = st.session_state.get("run_id")
    if not run_id:
        upload_form(settings)
        return

    show_run(str(run_id))


def sidebar() -> dict[str, Any]:
    st.header("Параметры")
    st.session_state["base_url"] = st.text_input(
        "Адрес сервиса",
        value=st.session_state.get("base_url")
        or os.environ.get("DECKFORGE_API_URL", DEFAULT_BASE_URL),
    )
    settings = {
        "variant": st.radio("Вариант вёрстки", ["A", "B", "C"], horizontal=True),
        "purpose": st.text_input("Зачем колода", value="report"),
        "audience": st.text_input("Кому", value="правление"),
        "target_slides": st.number_input("Слайдов", min_value=1, max_value=60, value=12),
        "language": st.selectbox("Язык", ["ru", "en"]),
        "seed": st.number_input("Seed", value=1337, help="Один и тот же seed даёт ту же колоду"),
        # Выключенный флажок означает «чини по конфигу и не спрашивай»: так прогон
        # не остановится посреди записи демо, если смотреть за ним некому.
        "interactive": st.checkbox("Спросить меня перед починкой находок", value=True),
    }
    if st.session_state.get("run_id"):
        st.divider()
        if st.button("Начать заново", use_container_width=True):
            forget_run()
    return settings


def upload_form(settings: dict[str, Any]) -> None:
    st.subheader("1. Шаблон")
    template = st.file_uploader("Файл .pptx или .potx", type=["pptx", "potx"])

    st.subheader("2. Материалы")
    materials = st.file_uploader(
        "Тексты, таблицы, картинки — сколько угодно файлов",
        accept_multiple_files=True,
    )

    ready = template is not None and bool(materials)
    if not st.button("Собрать презентацию", type="primary", disabled=not ready):
        return

    try:
        run_id = send(settings, template, materials or [])
    except ServiceError as error:
        st.error(f"Сервис отказал — {error.detail}")
        return
    # До сервиса не дошло вовсе: сеть, адрес, контейнер. Причину показываем как есть.
    except Exception as error:
        st.error(f"Не удалось связаться с сервисом: {error}")
        return

    st.session_state["run_id"] = run_id
    st.rerun()


def send(settings: dict[str, Any], template: Any, materials: list[Any]) -> str:
    """Создать прогон, загрузить файлы, запустить. Порядок важен: старт — последним."""
    api = client()
    run_id = api.create_run(
        variant=str(settings["variant"]),
        purpose=str(settings["purpose"]),
        audience=str(settings["audience"]),
        target_slides=int(settings["target_slides"]),
        language=str(settings["language"]),
        seed=int(settings["seed"]),
        interactive=bool(settings["interactive"]),
    )
    api.upload_template(run_id, template.name, template.getvalue())
    for item in materials:
        api.upload_content(run_id, item.name, item.getvalue())
    api.start(run_id)
    return run_id


def show_run(run_id: str) -> None:
    api = client()
    try:
        status = api.status(run_id)
    except ServiceError as error:
        st.error(f"Прогон не читается — {error.detail}")
        forget_run()
        return

    state = str(status.get("state", "queued"))
    progress(status, state)

    if state == "failed":
        st.error(status.get("error") or "Прогон не дошёл до конца, причина не названа")
    elif state == "waiting_choice":
        choose_fixes(run_id, api.findings(run_id))
    elif state == "done":
        finished(run_id, status)
    else:
        # Прогон идёт: страница перерисовывается сама, чтобы не жать «обновить».
        time.sleep(REFRESH_S)
        st.rerun()


def progress(status: dict[str, Any], state: str) -> None:
    label = STATE_LABELS.get(state, state)
    stage = status.get("stage")
    st.progress(
        float(status.get("progress", 0.0)),
        text=f"{label}{f' · стадия {stage}' if stage else ''} · {status.get('elapsed_s', 0)} с",
    )


def choose_fixes(run_id: str, findings: list[dict[str, Any]]) -> None:
    """Находки с подсветкой и выбор, что чинить."""
    st.subheader("Аудит нашёл, что можно поправить")
    st.caption(
        "Отмеченное будет исправлено автоматически, колода пересобрана и проверена заново. "
        "Можно не выбирать ничего — это тоже решение."
    )

    chosen: list[str] = []
    for slide_id, group in by_slide(findings).items():
        with st.container(border=True):
            picture, text = st.columns([2, 3])
            with picture:
                slide_preview(run_id, slide_id, group)
            with text:
                st.markdown(f"**Слайд {slide_id or '—'}**")
                for finding in group:
                    chosen.extend(finding_row(finding))

    left, right = st.columns(2)
    if left.button(f"Исправить выбранное ({len(chosen)})", type="primary", disabled=not chosen):
        send_choice(run_id, chosen)
    if right.button("Оставить как есть"):
        send_choice(run_id, [])


def slide_preview(run_id: str, slide_id: str, group: list[dict[str, Any]]) -> None:
    png = client().preview(run_id, slide_id) if slide_id else None
    if png is None:
        # Превью нет — LibreOffice недоступен или слайд не отрисован. Это не повод
        # прятать находки: место они называют словами, а не только рамкой.
        st.info("Превью этого слайда нет")
        return
    st.image(draw_findings(png, group), use_container_width=True)


def finding_row(finding: dict[str, Any]) -> list[str]:
    severity = str(finding.get("severity", "warning"))
    mark = {"error": "🔴", "warning": "🟠", "info": "🔵"}.get(severity, "⚪")
    finding_id = str(finding.get("finding_id"))
    message = str(finding.get("message") or finding.get("check_id"))

    if str(finding.get("auto_fix", "none")) == "none":
        # Чинить нечем — но показать надо: пользователь увидит это в отчёте и на слайде.
        st.markdown(f"{mark} {message}  \n*починить автоматически нельзя*")
        return []
    picked = st.checkbox(f"{mark} {message}", key=f"fix-{finding_id}")
    return [finding_id] if picked else []


def send_choice(run_id: str, finding_ids: list[str]) -> None:
    try:
        client().choose_fixes(run_id, finding_ids)
    except ServiceError as error:
        st.error(f"Выбор не принят — {error.detail}")
        return
    st.rerun()


def finished(run_id: str, status: dict[str, Any]) -> None:
    st.success("Колода собрана")
    if status.get("error"):
        # Дошло до конца, но что-то не отработало. Прятать это за зелёным статусом нельзя.
        # Деградации сюда больше не попадают: они не сбой, и их показывает `summary`.
        st.warning(status["error"])

    report = client().report(run_id) or {}
    if report:
        summary(report)

    st.subheader("Скачать")
    columns = st.columns(len(EXPORT_LABELS))
    for column, (fmt, label) in zip(columns, EXPORT_LABELS.items(), strict=True):
        data = client().export(run_id, fmt)
        with column:
            if data is None:
                st.button(label, disabled=True, use_container_width=True)
            else:
                st.download_button(
                    label, data, file_name=f"{run_id}.{fmt}", use_container_width=True
                )


def summary(report: dict[str, Any]) -> None:
    audit = report.get("audit") or {}
    numbers = st.columns(4)
    numbers[0].metric("Слайдов", report.get("slides", 0))
    numbers[1].metric("Время, с", report.get("total_s", 0))
    numbers[2].metric("Ошибок аудита", audit.get("errors", 0))
    numbers[3].metric("Предупреждений", audit.get("warnings", 0))

    for line in report.get("degradations") or []:
        # Деградация — не сбой: колода собрана более дешёвым путём (§15). Сказать об этом
        # надо, но не цветом ошибки, иначе удачный прогон выглядит как неудачный.
        st.info(line)
    for line in report.get("errors") or []:
        st.error(line)
    skipped = report.get("skipped_checks") or []
    if skipped:
        # Пропуск не равен прохождению — это правило аудита, и интерфейс его держит.
        st.info(f"Проверок пропущено: {len(skipped)} — {', '.join(skipped)}")

    with st.expander("Отчёт прогона целиком"):
        st.json(report)


def forget_run() -> None:
    for key in [k for k in st.session_state if k == "run_id" or str(k).startswith("fix-")]:
        del st.session_state[key]
    st.rerun()


if __name__ == "__main__":
    main()
