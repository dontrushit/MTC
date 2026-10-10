"""Who opened what: the access journal. Answer to 'кто открывал звонок'."""

from datetime import datetime

import streamlit as st

from app.ui.api_client import ApiError, api_get
from app.ui.theme import configure, page_heading

user = configure("Журнал доступов")


def _when(raw: str) -> str:
    try:
        moment = datetime.fromisoformat(str(raw))
    except ValueError:
        return str(raw)
    return moment.strftime("%d.%m.%Y %H:%M")


try:
    page_heading("Журнал доступов")
    if not user.get("is_supervisor"):
        st.info("Журнал видит ответственный сотрудник.")
        st.stop()
    rows = api_get("/audit", params={"limit": 200})
    if not rows:
        st.caption("Пока никто ничего не открывал.")
        st.stop()
    table = [
        {
            "Когда": _when(row.get("at")),
            "Кто": row.get("manager_name") or "система",
            "Действие": row.get("action_ru") or row.get("action"),
            "Что": (
                f"{row.get('entity')} #{row.get('entity_id')}"
                if row.get("entity_id") is not None
                else str(row.get("entity"))
            ),
            "Детали": row.get("detail") or "",
        }
        for row in rows
    ]
    st.dataframe(table, use_container_width=True, hide_index=True)
except ApiError as exc:
    st.error(exc.message)
