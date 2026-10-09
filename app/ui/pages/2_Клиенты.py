"""Client card: name, surname, phone, and a report for every call."""

import streamlit as st

from app.ui.api_client import ApiError, api_delete, api_get, api_patch
from app.ui.labels import format_dt
from app.ui.theme import (
    configure,
    page_heading,
    show_agreement,
    show_client,
    show_dialog,
    show_section,
)

configure("Клиенты")


def main() -> None:
    page_heading("Клиенты")
    query = st.text_input("Поиск", placeholder="Имя, фамилия или номер")
    clients = api_get("/clients", params={"q": query.strip()})
    if not clients:
        st.info("Ничего не найдено.")
        return

    if len(clients) == 1:
        client_id = clients[0]["id"]
    else:
        client_id = st.selectbox(
            "Клиент",
            options=[item["id"] for item in clients],
            format_func=lambda item_id: _label(clients, item_id),
            label_visibility="collapsed",
        )
    card = api_get(f"/clients/{client_id}")
    if st.session_state.get("edit_client") == card["id"]:
        _edit_form(card)
        return
    show_client(card)
    _client_actions(card)

    show_section("Звонки")
    if not card["calls"]:
        st.caption("Звонков пока нет.")
        return
    for call in card["calls"]:
        with st.expander(format_dt(call["started_at"])):
            _render_call(call)
            _delete_call(call["id"])


def _render_call(call: dict) -> None:
    if call["status"] == "error" and call.get("error_message"):
        st.error(call["error_message"])
        return
    if call["status"] != "extracted":
        st.caption("Отчёт ещё готовится.")
        return
    detail = api_get(f"/calls/{call['id']}")
    show_dialog(detail["utterances"])
    if detail["agreements"]:
        for agreement in detail["agreements"]:
            show_agreement(agreement)
    else:
        st.caption("Договорённостей в этом разговоре не найдено.")


def _client_actions(card: dict) -> None:
    edit, remove = st.columns(2)
    if edit.button("Изменить", key=f"edit-{card['id']}"):
        st.session_state["edit_client"] = card["id"]
        st.session_state.pop("confirm_delete", None)
        st.rerun()
    if st.session_state.get("confirm_delete") == card["id"]:
        st.warning("Удалятся клиент и все его звонки.")
        if remove.button("Удалить навсегда", key=f"confirm-{card['id']}"):
            api_delete(f"/clients/{card['id']}")
            st.session_state.pop("confirm_delete", None)
            st.rerun()
        return
    if remove.button("Удалить", key=f"delete-{card['id']}"):
        st.session_state["confirm_delete"] = card["id"]
        st.rerun()


def _edit_form(card: dict) -> None:
    name = st.text_input("Имя", value=card["name"])
    last_name = st.text_input("Фамилия", value=card.get("last_name") or "")
    phone = st.text_input("Номер", value=card["phone"])
    save, cancel = st.columns(2)
    if save.button("Сохранить", type="primary"):
        if not name.strip() or not last_name.strip() or not phone.strip():
            st.warning("Нужны имя, фамилия и номер.")
            return
        api_patch(
            f"/clients/{card['id']}",
            {
                "name": name.strip(),
                "last_name": last_name.strip(),
                "phone": phone.strip(),
            },
        )
        st.session_state.pop("edit_client", None)
        st.rerun()
    if cancel.button("Отмена"):
        st.session_state.pop("edit_client", None)
        st.rerun()


def _delete_call(call_id: int) -> None:
    pending = f"pending-call-{call_id}"
    if st.session_state.get(pending):
        if st.button("Удалить этот звонок", key=f"do-call-{call_id}"):
            api_delete(f"/calls/{call_id}")
            st.session_state.pop(pending, None)
            st.rerun()
        return
    if st.button("Удалить звонок", key=f"ask-call-{call_id}"):
        st.session_state[pending] = True
        st.rerun()


def _label(clients: list[dict], client_id: int) -> str:
    client = next(item for item in clients if item["id"] == client_id)
    full = " ".join(part for part in (client.get("name"), client.get("last_name")) if part)
    return f"{full} — {client['phone']}"


try:
    main()
except ApiError as exc:
    st.error(exc.message)
