"""PBX connection settings. Recording itself is switched on in the MTS cabinet."""

import streamlit as st

from app.ui.api_client import ApiError, api_get, api_post, api_put
from app.ui.theme import configure, page_heading

user = configure("Настройка АТС")


def _form(data: dict) -> None:
    st.text_input("Адрес для кабинета МТС", value=data["event_url"], disabled=True)
    with st.form("atc_settings"):
        recording_url = st.text_input(
            "Ссылка на запись",
            value=data.get("recording_url") or "",
            placeholder="https://сервер/recordings/{call_id}",
        )
        managers = _manager_phones(data)
        if st.form_submit_button("Сохранить", type="primary"):
            if any(not item["name"] for item in managers):
                st.warning("Нужно имя сотрудника.")
                return
            api_put(
                "/atc/settings",
                {
                    "public_url": data.get("public_url") or "",
                    "basic_user": data.get("basic_user") or "",
                    "basic_password": data.get("basic_password") or "",
                    "recording_url": recording_url.strip(),
                    "manager_id": data.get("manager_id"),
                    "managers": managers,
                },
            )
            st.session_state["atc_saved"] = True
            st.rerun()


def _manager_phones(data: dict) -> list[dict]:
    rows = list(data.get("managers") or [])
    if not rows:
        st.caption("Сначала добавьте сотрудника.")
        return []
    people = []
    for item in rows:
        name_key = f"mgr-name-{item['id']}"
        phone_key = f"mgr-phone-{item['id']}"
        if name_key not in st.session_state:
            st.session_state[name_key] = item["name"]
        if phone_key not in st.session_state:
            st.session_state[phone_key] = item.get("phone") or ""
        name = st.text_input("Сотрудник", key=name_key)
        phone = st.text_input(
            "Короткий номер в Автосекретаре",
            placeholder="Короткий номер",
            key=phone_key,
        )
        password = st.text_input(
            "Пароль для входа",
            type="password",
            placeholder="Не менять",
            key=f"mgr-pass-{item['id']}",
        )
        people.append(
            {
                "id": int(item["id"]),
                "name": name.strip(),
                "phone": phone.strip(),
                "password": password,
            }
        )
    return people


def _add_employee() -> None:
    with st.form("new_employee"):
        st.caption("Новый сотрудник")
        name = st.text_input("Имя")
        password = st.text_input("Пароль", type="password")
        phone = st.text_input("Короткий номер в Автосекретаре", placeholder="Короткий номер")
        if st.form_submit_button("Добавить"):
            if not name.strip() or len(password) < 4:
                st.warning("Нужны имя и пароль.")
                return
            api_post(
                "/managers",
                json={"name": name.strip(), "password": password, "phone": phone.strip()},
            )
            st.rerun()


try:
    if not user.get("is_supervisor"):
        page_heading("Настройка АТС")
        st.info("Настройку АТС меняет ответственный сотрудник.")
        st.stop()
    page_heading("Настройка АТС")
    if st.session_state.pop("atc_saved", None):
        st.success("Сохранено.")
    _form(api_get("/atc/settings"))
    _add_employee()
except ApiError as exc:
    st.error(exc.message)
