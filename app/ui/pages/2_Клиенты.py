"""Client card: name, surname, phone, and a report for every call."""

import streamlit as st

from app.ui.api_client import ApiError, api_delete, api_get, api_patch, api_post
from app.ui.labels import format_dt
from app.ui.theme import (
    configure,
    page_heading,
    show_call_extras,
    show_call_report,
    show_client,
    show_section,
)

configure("Клиенты")

_SORTS = {"Имя": "name", "Фамилия": "last_name", "Дата звонка": "call"}


def main() -> None:
    page_heading("Клиенты")
    _add_client()
    search, order = st.columns([2, 1])
    if st.session_state.pop("clients_clear_search", False):
        st.session_state["clients_query"] = ""
    query = search.text_input(
        "Поиск",
        placeholder="Имя, фамилия или номер",
        key="clients_query",
    )
    sort_label = order.selectbox("Сортировка", list(_SORTS))
    clients = api_get("/clients", params={"q": query.strip(), "sort": _SORTS[sort_label]})
    if not clients:
        st.info("Ничего не найдено.")
        return

    options = [item["id"] for item in clients]
    chosen = st.session_state.pop("clients_select_id", None)
    if chosen in options:
        st.session_state["client_pick"] = chosen
    elif st.session_state.get("client_pick") not in options:
        st.session_state.pop("client_pick", None)
    client_id = st.radio(
        "Клиент",
        options=options,
        index=None,
        format_func=lambda item_id: _label(clients, item_id),
        key="client_pick",
    )
    if client_id is None:
        return
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


def _add_client() -> None:
    with st.expander("Новый клиент"):
        if st.session_state.pop("clients_clear_form", False):
            st.session_state["clients_new_name"] = ""
            st.session_state["clients_new_last"] = ""
            st.session_state["clients_new_phone"] = ""
        name = st.text_input("Имя", key="clients_new_name")
        last_name = st.text_input("Фамилия", key="clients_new_last")
        phone = st.text_input("Номер", key="clients_new_phone")
        if st.button("Добавить клиента", type="primary", key="clients_add"):
            if not name.strip() or not last_name.strip() or not phone.strip():
                st.warning("Нужны имя, фамилия и номер.")
                return
            created = api_post(
                "/clients",
                json={
                    "name": name.strip(),
                    "last_name": last_name.strip(),
                    "phone": phone.strip(),
                },
            )
            st.session_state["clients_select_id"] = int(created["id"])
            st.session_state["clients_clear_form"] = True
            st.session_state["clients_clear_search"] = True
            st.rerun()


def _render_call(call: dict) -> None:
    detail = api_get(f"/calls/{call['id']}")
    if call["status"] == "error" and call.get("error_message"):
        st.error(call["error_message"])
    elif call["status"] != "extracted":
        st.caption("Отчёт ещё готовится.")
    else:
        show_call_report(detail, detail["agreements"])
    show_call_extras(detail)


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
