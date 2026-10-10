"""Recent calls: who, when, and whether the recording or the report is ready."""

import html
from datetime import timedelta

import streamlit as st

from app.ui.api_client import ApiError, api_delete, api_get
from app.ui.labels import format_dt, history_status_ru
from app.ui.theme import configure, page_heading, show_call_extras

configure("История")


def _row(item: dict, index: int) -> None:
    title = item.get("client_name") or "Новый звонок"
    bits = [format_dt(item.get("started_at"))]
    if item.get("phone"):
        bits.append(str(item["phone"]))
    if item.get("topic"):
        bits.append(str(item["topic"]))
    status = html.escape(str(item.get("status") or ""))
    with st.container(border=True, key=f"history-{index}"):
        st.html(
            "<article class='mts-history'>"
            "<div>"
            f"<strong>{html.escape(title)}</strong>"
            f"<span>{html.escape(' · '.join(bits))}</span>"
            "</div>"
            f"<em class='mts-history-{status}'>{html.escape(history_status_ru(status))}</em>"
            "</article>"
        )
        if item.get("status") == "error" and item.get("error_message"):
            st.error(str(item["error_message"]))
        call_id = item.get("call_id")
        if call_id:
            _extras(int(call_id), item.get("status") == "ready")
            _delete_call(int(call_id))


def _extras(call_id: int, ready: bool) -> None:
    report_open = ready and bool(st.session_state.get(f"report-open-{call_id}"))
    dialog_open = bool(st.session_state.get(f"dialog-open-{call_id}"))
    audio_open = bool(st.session_state.get(f"audio-open-{call_id}"))
    if report_open or dialog_open or audio_open:
        detail = api_get(f"/calls/{call_id}")
    else:
        detail = {"id": call_id}
    show_call_extras(detail, with_report=ready)


def _delete_call(call_id: int) -> None:
    pending = f"history-del-{call_id}"
    if st.session_state.get(pending):
        st.caption("Удалится этот звонок и его запись.")
        if st.button("Удалить навсегда", key=f"history-do-{call_id}"):
            api_delete(f"/calls/{call_id}")
            st.session_state.pop(pending, None)
            st.rerun()
        return
    if st.button("Удалить", key=f"history-ask-{call_id}"):
        st.session_state[pending] = True
        st.rerun()


@st.fragment(run_every=timedelta(seconds=3))
def _journal() -> None:
    try:
        items = api_get("/history")
    except ApiError as exc:
        st.error(exc.message)
        return
    if not items:
        st.info("Звонков пока нет.")
        return
    for index, item in enumerate(items):
        _row(item, index)


try:
    page_heading("История", "Последние звонки и их статус.")
    _journal()
except ApiError as exc:
    st.error(exc.message)
