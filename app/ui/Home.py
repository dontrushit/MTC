"""Call screen: record or upload, then show the report."""

import time as time_module
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from app.config import settings
from app.ui.api_client import ApiError, api_get, api_patch, api_post
from app.ui.labels import call_status_ru, format_dt
from app.ui.phone_form import client_phone_input
from app.ui.theme import (
    configure,
    page_heading,
    show_call_extras,
    show_call_report,
    show_live_call,
    show_section,
)

user = configure("Звонок")


def _show_progress() -> None:
    call_id = st.session_state.get("active_call_id")
    if not call_id:
        return
    call = api_get(f"/calls/{call_id}")
    status = call["status"]
    if status == "error":
        st.error(call.get("error_message") or "Не удалось разобрать запись.")
        return
    if status == "extracted":
        return
    st.info(f"Звонок #{call_id}: {call_status_ru(status)}. Это займёт немного времени.")
    time_module.sleep(3)
    st.rerun()


def _show_report() -> None:
    call_id = st.session_state.get("active_call_id")
    if not call_id:
        return
    call = api_get(f"/calls/{call_id}")
    if call["status"] != "extracted":
        return
    show_section("Отчёт")
    st.caption(format_dt(call.get("started_at")))
    show_call_report(call, call["agreements"])
    show_call_extras(call)
    for agreement in call["agreements"]:
        _done_button(agreement)


def _done_button(agreement: dict) -> None:
    if agreement["status"] not in ("open", "overdue"):
        return
    if st.button("Выполнена", key=f"done-{agreement['id']}"):
        api_patch(f"/agreements/{agreement['id']}", {"status": "done"})
        st.rerun()


@st.fragment(run_every=timedelta(seconds=2))
def _live_recording() -> None:
    """Refresh only this banner, so a new PBX call shows that recording started."""
    try:
        live = api_get("/atc/live")
    except ApiError:
        return
    show_live_call(str(live.get("phase") or "idle"), str(live.get("caller_phone") or ""))


def main() -> None:
    page_heading("Звонок", "Нажмите микрофон в начале разговора и остановите в конце.")
    _live_recording()
    clients = api_get("/clients")
    _call_form(int(user["id"]), clients)
    _show_progress()
    _show_report()


def _call_form(manager_id: int, clients: list[dict]) -> None:
    client_id = _client_fields(clients)
    recorded = st.audio_input("Запись звонка", sample_rate=16000)
    if recorded is not None and recorded.getvalue():
        payload = recorded.getvalue()
        st.audio(payload, format="audio/wav")
        file_id = getattr(recorded, "file_id", None)
        if st.session_state.get("sent_audio_id") == file_id:
            st.caption("Эта запись уже разобрана.")
        elif st.button("Разобрать", type="primary"):
            _submit_audio(
                manager_id,
                client_id,
                filename="recording.wav",
                payload=payload,
                content_type="audio/wav",
                started_at=datetime.now(ZoneInfo(settings.TZ)).isoformat(),
                file_id=file_id,
            )
    with st.expander("Загрузить готовый файл"):
        _file_source(manager_id, client_id)


def _file_source(manager_id: int, client_id: int | None) -> None:
    uploaded = st.file_uploader(
        "Файл",
        type=["wav", "mp3", "m4a", "ogg", "flac"],
        label_visibility="collapsed",
    )
    call_date = st.date_input("Дата звонка", value=date.today())
    if st.button("Разобрать файл"):
        if uploaded is None:
            st.warning("Выберите аудиофайл.")
            return
        started = datetime.combine(call_date, datetime.now().time()).isoformat()
        _submit_audio(
            manager_id,
            client_id,
            filename=uploaded.name,
            payload=uploaded.getvalue(),
            content_type=uploaded.type or "application/octet-stream",
            started_at=started,
            file_id=None,
        )


def _submit_audio(
    manager_id: int,
    client_id: int | None,
    *,
    filename: str,
    payload: bytes,
    content_type: str,
    started_at: str,
    file_id: str | None,
) -> None:
    if not payload:
        st.warning("Запись пустая.")
        return
    if client_id is None:
        st.warning("Выберите клиента или добавьте нового.")
        return
    result = api_post(
        "/calls",
        data={
            "client_id": str(client_id),
            "manager_id": str(manager_id),
            "started_at": started_at,
        },
        files={"file": (filename, payload, content_type)},
    )
    if file_id is not None:
        st.session_state["sent_audio_id"] = file_id
    st.session_state["active_call_id"] = result["id"]
    st.rerun()


def _client_fields(clients: list[dict]) -> int | None:
    client_id = None
    if clients:
        ids = [item["id"] for item in clients]
        chosen = st.session_state.pop("select_client_id", None)
        if chosen in ids:
            st.session_state["call_client"] = chosen
        client_id = st.selectbox(
            "Клиент",
            options=ids,
            format_func=lambda item_id: _client_label(clients, item_id),
            key="call_client",
        )
    else:
        st.caption("Клиентов пока нет — заполните нового.")
    with st.expander("Новый клиент", expanded=not clients):
        if st.session_state.pop("clear_new_client", False):
            st.session_state["new_client_name"] = ""
            st.session_state["new_client_last"] = ""
            st.session_state["new_client_phone"] = ""
            st.session_state["new-op"] = ""
            st.session_state["new-num"] = ""
            st.session_state["new_client_contract"] = ""
        name = st.text_input("Имя", key="new_client_name")
        last_name = st.text_input("Фамилия", key="new_client_last")
        phone = client_phone_input("new")
        contract_number = st.text_input(
            "Номер договора",
            key="new_client_contract",
            placeholder="Необязательно",
        )
        if st.button("Добавить клиента", type="primary"):
            if not name.strip() or not last_name.strip() or not phone:
                st.warning("Нужны имя, фамилия и номер: +375, код и 7 цифр.")
            else:
                created = api_post(
                    "/clients",
                    json={
                        "name": name.strip(),
                        "last_name": last_name.strip(),
                        "phone": phone,
                        "contract_number": contract_number.strip(),
                    },
                )
                st.session_state["select_client_id"] = int(created["id"])
                st.session_state["clear_new_client"] = True
                st.rerun()
    return int(client_id) if client_id is not None else None


def _client_label(clients: list[dict], client_id: int) -> str:
    client = next(item for item in clients if item["id"] == client_id)
    full = " ".join(part for part in (client.get("name"), client.get("last_name")) if part)
    bits = [full, client["phone"]]
    if client.get("contract_number"):
        bits.append(str(client["contract_number"]))
    return " — ".join(bits)


try:
    main()
except ApiError as exc:
    st.error(exc.message)
