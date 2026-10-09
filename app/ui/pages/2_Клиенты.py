"""Client card: name, surname, phone, and a report for every call."""

import streamlit as st

from app.ui.api_client import ApiError, api_get
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
    show_client(card)

    show_section("Звонки")
    if not card["calls"]:
        st.caption("Звонков пока нет.")
        return
    for call in card["calls"]:
        with st.expander(format_dt(call["started_at"])):
            _render_call(call)


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


def _label(clients: list[dict], client_id: int) -> str:
    client = next(item for item in clients if item["id"] == client_id)
    full = " ".join(part for part in (client.get("name"), client.get("last_name")) if part)
    return f"{full} — {client['phone']}"


try:
    main()
except ApiError as exc:
    st.error(exc.message)
