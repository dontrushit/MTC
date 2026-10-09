"""Call screen: record or upload, then show the report."""

import time as time_module
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from app.config import settings
from app.ui.api_client import ApiError, api_get, api_get_bytes, api_patch, api_post
from app.ui.labels import call_status_ru, format_dt
from app.ui.theme import (
    configure,
    page_heading,
    show_agreement,
    show_dialog,
    show_section,
)

configure("Звонок")

_AUDIO_FORMATS = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


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
    try:
        audio, media = api_get_bytes(f"/calls/{call_id}/audio")
    except ApiError as exc:
        st.warning(exc.message)
    else:
        st.audio(audio, format=_audio_format(call["audio_path"], media))
    show_dialog(call["utterances"])
    if call["agreements"]:
        show_section("Договорённости")
        for agreement in call["agreements"]:
            show_agreement(agreement)
            _done_button(agreement)
    else:
        st.caption("Договорённостей в этом разговоре не найдено.")


def _done_button(agreement: dict) -> None:
    if agreement["status"] not in ("open", "overdue"):
        return
    if st.button("Выполнена", key=f"done-{agreement['id']}"):
        api_patch(f"/agreements/{agreement['id']}", {"status": "done"})
        st.rerun()


def main() -> None:
    page_heading("Звонок", "Нажмите микрофон в начале разговора и остановите в конце.")
    managers = api_get("/managers")
    clients = api_get("/clients")
    if not managers:
        st.warning("Нет менеджеров. Создайте менеджера через API или scripts/seed_demo.py.")
        return
    _call_form(managers, clients)
    _show_progress()
    _show_report()


def _call_form(managers: list[dict], clients: list[dict]) -> None:
    manager_id = _manager_id(managers)
    client_id, new_client = _client_fields(clients)
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
                new_client,
                filename="recording.wav",
                payload=payload,
                content_type="audio/wav",
                started_at=datetime.now(ZoneInfo(settings.TZ)).isoformat(),
                file_id=file_id,
            )
    with st.expander("Загрузить готовый файл"):
        _file_source(manager_id, client_id, new_client)


def _file_source(
    manager_id: int,
    client_id: int | None,
    new_client: dict[str, str],
) -> None:
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
            new_client,
            filename=uploaded.name,
            payload=uploaded.getvalue(),
            content_type=uploaded.type or "application/octet-stream",
            started_at=started,
            file_id=None,
        )


def _submit_audio(
    manager_id: int,
    client_id: int | None,
    new_client: dict[str, str],
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
    target_id = _resolve_client(client_id, new_client)
    if target_id is None:
        return
    result = api_post(
        "/calls",
        data={
            "client_id": str(target_id),
            "manager_id": str(manager_id),
            "started_at": started_at,
        },
        files={"file": (filename, payload, content_type)},
    )
    if file_id is not None:
        st.session_state["sent_audio_id"] = file_id
    st.session_state["active_call_id"] = result["id"]
    st.rerun()


def _manager_id(managers: list[dict]) -> int:
    if len(managers) == 1:
        return int(managers[0]["id"])
    names = {item["id"]: item["name"] for item in managers}
    return int(
        st.selectbox(
            "Менеджер",
            options=list(names),
            format_func=lambda item_id: names[item_id],
        )
    )


def _client_fields(clients: list[dict]) -> tuple[int | None, dict[str, str]]:
    client_id = None
    if clients:
        client_id = st.selectbox(
            "Клиент",
            options=[item["id"] for item in clients],
            format_func=lambda item_id: _client_label(clients, item_id),
        )
    else:
        st.caption("Клиентов пока нет — заполните нового.")
    with st.expander("Новый клиент", expanded=not clients):
        name = st.text_input("Имя")
        last_name = st.text_input("Фамилия")
        phone = st.text_input("Номер")
    return client_id, {
        "name": name.strip(),
        "last_name": last_name.strip(),
        "phone": phone.strip(),
    }


def _resolve_client(client_id: int | None, new_client: dict[str, str]) -> int | None:
    if new_client["name"] and new_client["last_name"] and new_client["phone"]:
        created = api_post(
            "/clients",
            json={
                "name": new_client["name"],
                "last_name": new_client["last_name"],
                "phone": new_client["phone"],
            },
        )
        return int(created["id"])
    if new_client["name"] or new_client["last_name"] or new_client["phone"]:
        st.warning("Для нового клиента нужны имя, фамилия и номер.")
        return None
    if client_id is None:
        st.warning("Выберите клиента или создайте нового.")
        return None
    return client_id


def _client_label(clients: list[dict], client_id: int) -> str:
    client = next(item for item in clients if item["id"] == client_id)
    full = " ".join(part for part in (client.get("name"), client.get("last_name")) if part)
    return f"{full} — {client['phone']}"


def _audio_format(path: str, media: str) -> str:
    if media.startswith("audio/"):
        return media
    return _AUDIO_FORMATS.get(Path(path).suffix.lower(), "audio/wav")


try:
    main()
except ApiError as exc:
    st.error(exc.message)
