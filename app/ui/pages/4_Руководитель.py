"""Supervisor view: per-manager stats and every overdue agreement."""

import streamlit as st

from app.ui.api_client import ApiError, api_get
from app.ui.labels import format_percent, responsible_ru

st.set_page_config(page_title="Руководитель", page_icon="📊", layout="wide")


def main() -> None:
    st.title("Руководитель")
    stats = api_get("/stats/managers")
    rows = [
        {
            "Менеджер": item["name"],
            "Открытые": item["open"],
            "Просроченные": item["overdue"],
            "Выполненные": item["done"],
            "В срок, %": format_percent(item["done_on_time"]),
        }
        for item in stats
    ]
    st.subheader("Менеджеры")
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("Менеджеров пока нет.")

    st.subheader("Просроченные")
    overdue = api_get("/agreements", params={"status": "overdue"})
    if not overdue:
        st.caption("Просроченных договорённостей нет.")
        return

    clients = {item["id"]: item["name"] for item in api_get("/clients")}
    calls = {item["id"]: item for item in api_get("/calls")}
    managers = {item["id"]: item["name"] for item in api_get("/managers")}

    table = []
    for agreement in overdue:
        call = calls.get(agreement["call_id"], {})
        manager_name = managers.get(call.get("manager_id"), "—")
        table.append(
            {
                "Клиент": clients.get(agreement["client_id"], "—"),
                "Менеджер": manager_name,
                "Действие": agreement["action"],
                "Ответственный": responsible_ru(agreement["responsible"]),
                "Срок": agreement.get("due_date") or "—",
                "Цитата": agreement.get("quote") or "",
            }
        )
    st.dataframe(table, hide_index=True, use_container_width=True)


try:
    main()
except ApiError as exc:
    st.error(exc.message)
