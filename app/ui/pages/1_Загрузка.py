"""Upload a call and poll its status."""

import time as time_module
from datetime import date, datetime, time

import streamlit as st

from app.ui.api_client import ApiError, api_get, api_post
from app.ui.labels import call_status_ru, format_dt

st.set_page_config(page_title="Загрузка", page_icon="📞", layout="wide")


def _show_status() -> None:
    call_id = st.session_state.get("active_call_id")
    if not call_id:
        return
    call = api_get(f"/calls/{call_id}")
    status = call["status"]
    st.subheader(f"Звонок #{call_id}")
    st.write(f"Статус: **{call_status_ru(status)}**")
    st.write(f"Дата звонка: {format_dt(call.get('started_at'))}")
    if status == "error" and call.get("error_message"):
        st.error(call["error_message"])
    if status == "extracted":
        st.success("Договорённости извлечены.")
    if status in ("extracted", "error"):
        if st.button("Скрыть статус"):
            st.session_state.pop("active_call_id", None)
            st.rerun()
        return
    st.caption("Статус обновляется каждые 3 секунды.")
    time_module.sleep(3)
    st.rerun()


def main() -> None:
    st.title("Загрузка звонка")
    managers = api_get("/managers")
    clients = api_get("/clients")
    if not managers:
        st.warning("Нет менеджеров. Создайте менеджера через API или scripts/seed_demo.py.")
        return

    manager_names = {item["id"]: item["name"] for item in managers}
    manager_id = st.selectbox(
        "Менеджер",
        options=list(manager_names),
        format_func=lambda item_id: manager_names[item_id],
    )
    mode = st.radio("Клиент", options=["существующий", "новый"], horizontal=True)
    client_id: int | None = None
    new_client: dict[str, str] | None = None
    if mode == "существующий":
        if not clients:
            st.info("Клиентов пока нет — заполните форму нового клиента.")
        else:
            client_id = st.selectbox(
                "Карточка клиента",
                options=[item["id"] for item in clients],
                format_func=lambda item_id: _client_label(clients, item_id),
            )
    else:
        name = st.text_input("Имя клиента")
        phone = st.text_input("Телефон")
        company = st.text_input("Компания")
        new_client = {"name": name.strip(), "phone": phone.strip(), "company": company.strip()}

    uploaded = st.file_uploader(
        "Запись звонка",
        type=["wav", "mp3", "m4a", "ogg", "flac"],
    )
    call_date = st.date_input("Дата звонка", value=date.today())
    call_time = st.time_input("Время звонка", value=time(11, 0))

    if st.button("Загрузить", type="primary"):
        if uploaded is None:
            st.warning("Выберите аудиофайл.")
        elif mode == "существующий" and client_id is None:
            st.warning("Выберите клиента или создайте нового.")
        elif mode == "новый" and new_client is not None and (
            not new_client["name"] or not new_client["phone"]
        ):
            st.warning("Укажите имя и телефон нового клиента.")
        else:
            target_id = client_id
            if mode == "новый" and new_client is not None:
                created = api_post(
                    "/clients",
                    json={
                        "name": new_client["name"],
                        "phone": new_client["phone"],
                        "company": new_client["company"] or None,
                    },
                )
                target_id = created["id"]
            started = datetime.combine(call_date, call_time).isoformat()
            result = api_post(
                "/calls",
                data={
                    "client_id": str(target_id),
                    "manager_id": str(manager_id),
                    "started_at": started,
                },
                files={
                    "file": (
                        uploaded.name,
                        uploaded.getvalue(),
                        uploaded.type or "application/octet-stream",
                    )
                },
            )
            st.session_state["active_call_id"] = result["id"]
            st.rerun()

    _show_status()


def _client_label(clients: list[dict], client_id: int) -> str:
    client = next(item for item in clients if item["id"] == client_id)
    company = f", {client['company']}" if client.get("company") else ""
    return f"{client['name']}{company}"


try:
    main()
except ApiError as exc:
    st.error(exc.message)
