"""Filter agreements and update status or due date in the row."""

from datetime import date

import streamlit as st

from app.ui.api_client import ApiError, api_get, api_patch
from app.ui.labels import agreement_status_ru, responsible_ru

st.set_page_config(page_title="Договорённости", page_icon="✅", layout="wide")

_STATUS_FILTERS = {
    "все": None,
    "открыта": "open",
    "просрочена": "overdue",
    "выполнена": "done",
    "отменена": "cancelled",
}
_RESPONSIBLE_FILTERS = {"все": None, "менеджер": "manager", "клиент": "client"}


def _edit_options(current: str) -> list[str]:
    options = [current]
    for item in ("done", "cancelled"):
        if item not in options:
            options.append(item)
    return options


def main() -> None:
    st.title("Договорённости")
    managers = api_get("/managers")
    manager_labels = {"все": None}
    for manager in managers:
        manager_labels[manager["name"]] = manager["id"]

    filters = st.columns(4)
    status_label = filters[0].selectbox("Статус", list(_STATUS_FILTERS))
    responsible_label = filters[1].selectbox("Ответственный", list(_RESPONSIBLE_FILTERS))
    manager_label = filters[2].selectbox("Менеджер", list(manager_labels))
    due_before = filters[3].date_input("Срок до", value=None)

    params = {
        "status": _STATUS_FILTERS[status_label],
        "responsible": _RESPONSIBLE_FILTERS[responsible_label],
        "manager_id": manager_labels[manager_label],
        "due_before": due_before.isoformat()[:10] if isinstance(due_before, date) else None,
    }
    agreements = api_get("/agreements", params=params)
    clients = {item["id"]: item["name"] for item in api_get("/clients")}

    if not agreements:
        st.info("Нет договорённостей по этим фильтрам.")
        return

    header = st.columns([3, 2, 2, 2, 2])
    header[0].markdown("**Действие**")
    header[1].markdown("**Клиент**")
    header[2].markdown("**Ответственный**")
    header[3].markdown("**Статус**")
    header[4].markdown("**Срок**")

    for agreement in agreements:
        row = st.columns([3, 2, 2, 2, 2])
        row[0].write(agreement["action"])
        if agreement.get("quote"):
            row[0].caption(f"«{agreement['quote']}»")
        row[1].write(clients.get(agreement["client_id"], "—"))
        row[2].write(responsible_ru(agreement["responsible"]))

        options = _edit_options(agreement["status"])
        chosen = row[3].selectbox(
            "Статус",
            options=options,
            index=options.index(agreement["status"]),
            format_func=agreement_status_ru,
            key=f"status-{agreement['id']}",
            label_visibility="collapsed",
        )
        if chosen in ("done", "cancelled") and chosen != agreement["status"]:
            api_patch(f"/agreements/{agreement['id']}", {"status": chosen})
            st.rerun()

        if agreement.get("due_date"):
            current_due = date.fromisoformat(agreement["due_date"])
            new_due = row[4].date_input(
                "Срок",
                value=current_due,
                key=f"due-{agreement['id']}",
                label_visibility="collapsed",
            )
            if new_due != current_due:
                api_patch(
                    f"/agreements/{agreement['id']}",
                    {"due_date": new_due.isoformat()},
                )
                st.rerun()
        else:
            row[4].write("—")


try:
    main()
except ApiError as exc:
    st.error(exc.message)
