"""Client card: name, surname, phone, optional contract number, and call reports."""

import json
from datetime import date

import streamlit as st

from app.ui.api_client import ApiError, api_delete, api_get, api_patch, api_post
from app.ui.labels import format_dt
from app.ui.phone_form import client_phone_input
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
        placeholder="Имя, фамилия, номер или договор",
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
            st.session_state["clients-new-op"] = ""
            st.session_state["clients-new-num"] = ""
            st.session_state["clients_new_contract"] = ""
        name = st.text_input("Имя", key="clients_new_name")
        last_name = st.text_input("Фамилия", key="clients_new_last")
        phone = client_phone_input("clients-new")
        contract_number = st.text_input(
            "Номер договора",
            key="clients_new_contract",
            placeholder="Необязательно",
        )
        if st.button("Добавить клиента", type="primary", key="clients_add"):
            if not name.strip() or not last_name.strip() or not phone:
                st.warning("Нужны имя, фамилия и номер: +375, код и 7 цифр.")
                return
            created = api_post(
                "/clients",
                json={
                    "name": name.strip(),
                    "last_name": last_name.strip(),
                    "phone": phone,
                    "contract_number": contract_number.strip(),
                },
            )
            st.session_state["clients_select_id"] = int(created["id"])
            st.session_state["clients_clear_form"] = True
            st.session_state["clients_clear_search"] = True
            st.rerun()


def _render_call(call: dict) -> None:
    detail = api_get(f"/calls/{call['id']}")
    if st.session_state.get("edit_report") == call["id"]:
        _edit_report(detail)
        return
    if call["status"] == "error" and call.get("error_message"):
        st.error(call["error_message"])
    elif call["status"] != "extracted":
        st.caption("Отчёт ещё готовится.")
    else:
        show_call_report(detail, detail["agreements"])
        if st.button("Изменить отчёт", key=f"edit-report-{call['id']}"):
            st.session_state["edit_report"] = call["id"]
            _reset_report_form(detail)
            st.rerun()
    show_call_extras(detail)


def _report_fields(call: dict) -> dict[str, str]:
    raw = str(call.get("report_json") or "").strip()
    data: dict = {}
    if raw:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    return {
        "topic": str(data.get("topic") or call.get("report_topic") or ""),
        "brief": str(data.get("brief") or call.get("report_summary") or ""),
        "unresolved": str(data.get("unresolved") or ""),
    }


def _reset_report_form(detail: dict) -> None:
    call_id = detail["id"]
    fields = _report_fields(detail)
    st.session_state[f"rep-topic-{call_id}"] = fields["topic"]
    st.session_state[f"rep-brief-{call_id}"] = fields["brief"]
    st.session_state[f"rep-open-{call_id}"] = fields["unresolved"]
    rows = []
    for agreement in detail.get("agreements") or []:
        rows.append(
            {
                "id": agreement["id"],
                "action": agreement.get("action") or "",
                "responsible": agreement.get("responsible") or "manager",
                "due_date": agreement.get("due_date") or "",
                "amount": agreement.get("amount") or "",
                "conditions": agreement.get("conditions") or "",
            }
        )
    st.session_state[f"rep-rows-{call_id}"] = rows
    st.session_state[f"rep-drop-{call_id}"] = []


def _edit_report(detail: dict) -> None:
    call_id = int(detail["id"])
    if f"rep-rows-{call_id}" not in st.session_state:
        _reset_report_form(detail)
    st.text_input("Тема", key=f"rep-topic-{call_id}")
    st.text_area("Кратко", key=f"rep-brief-{call_id}")
    rows: list[dict] = st.session_state[f"rep-rows-{call_id}"]
    st.caption("Договорённости")
    for index, row in enumerate(rows):
        st.session_state.setdefault(f"rep-action-{call_id}-{index}", row["action"])
        st.session_state.setdefault(f"rep-who-{call_id}-{index}", row["responsible"])
        st.session_state.setdefault(f"rep-due-{call_id}-{index}", row["due_date"] or "")
        st.session_state.setdefault(f"rep-amount-{call_id}-{index}", row["amount"])
        st.session_state.setdefault(f"rep-cond-{call_id}-{index}", row["conditions"])
        st.text_input("Что сделать", key=f"rep-action-{call_id}-{index}")
        who, due, money = st.columns(3)
        who.selectbox(
            "Кто",
            ["manager", "client"],
            format_func=lambda item: "Менеджер" if item == "manager" else "Клиент",
            key=f"rep-who-{call_id}-{index}",
        )
        due.text_input("Срок", key=f"rep-due-{call_id}-{index}", placeholder="2026-10-15")
        money.text_input("Сумма", key=f"rep-amount-{call_id}-{index}")
        st.text_input("Условия", key=f"rep-cond-{call_id}-{index}")
        if st.button("Убрать", key=f"rep-del-{call_id}-{index}"):
            _capture_rows(call_id)
            current = rows[index]
            if current.get("id"):
                st.session_state[f"rep-drop-{call_id}"].append(current["id"])
            rows.pop(index)
            _forget_row_widgets(call_id)
            st.rerun()
    if st.button("Добавить договорённость", key=f"rep-add-{call_id}"):
        _capture_rows(call_id)
        rows.append(
            {
                "id": None,
                "action": "",
                "responsible": "client",
                "due_date": "",
                "amount": "",
                "conditions": "",
            }
        )
        st.rerun()
    st.text_area("Не решено", key=f"rep-open-{call_id}")
    save, cancel = st.columns(2)
    if save.button("Сохранить отчёт", type="primary", key=f"rep-save-{call_id}"):
        _save_report(call_id)
    if cancel.button("Отмена", key=f"rep-cancel-{call_id}"):
        _close_report_form(call_id)


def _capture_rows(call_id: int) -> None:
    rows: list[dict] = st.session_state[f"rep-rows-{call_id}"]
    for index, row in enumerate(rows):
        row["action"] = st.session_state.get(f"rep-action-{call_id}-{index}", row["action"])
        row["responsible"] = st.session_state.get(
            f"rep-who-{call_id}-{index}", row["responsible"]
        )
        row["due_date"] = st.session_state.get(f"rep-due-{call_id}-{index}", row["due_date"])
        row["amount"] = st.session_state.get(f"rep-amount-{call_id}-{index}", row["amount"])
        row["conditions"] = st.session_state.get(f"rep-cond-{call_id}-{index}", row["conditions"])


def _forget_row_widgets(call_id: int) -> None:
    prefix = "rep-"
    stale = [
        key
        for key in st.session_state
        if key.startswith(prefix)
        and any(
            key.startswith(f"rep-{name}-{call_id}-")
            for name in ("action", "who", "due", "amount", "cond", "del")
        )
    ]
    for key in stale:
        st.session_state.pop(key, None)


def _parse_due(text: str) -> str | None:
    raw = text.strip()
    if not raw:
        return None
    date.fromisoformat(raw)
    return raw


def _save_report(call_id: int) -> None:
    _capture_rows(call_id)
    rows: list[dict] = st.session_state[f"rep-rows-{call_id}"]
    parsed: list[tuple[dict, str | None]] = []
    for row in rows:
        action = str(row["action"]).strip()
        if not action:
            st.warning("У каждой договорённости должно быть действие.")
            return
        try:
            due = _parse_due(str(row["due_date"]))
        except ValueError:
            st.warning("Срок пишите как 2026-10-15 или оставьте поле пустым.")
            return
        parsed.append((row, due))
    api_patch(
        f"/calls/{call_id}/report",
        {
            "topic": st.session_state.get(f"rep-topic-{call_id}", ""),
            "brief": st.session_state.get(f"rep-brief-{call_id}", ""),
            "unresolved": st.session_state.get(f"rep-open-{call_id}", ""),
        },
    )
    for agreement_id in st.session_state.get(f"rep-drop-{call_id}", []):
        api_delete(f"/agreements/{agreement_id}")
    for row, due in parsed:
        payload = {
            "action": str(row["action"]).strip(),
            "responsible": row["responsible"],
            "due_date": due,
            "due_text": due or "",
            "amount": str(row["amount"]).strip(),
            "conditions": str(row["conditions"]).strip(),
        }
        if row.get("id"):
            api_patch(f"/agreements/{row['id']}", payload)
        else:
            api_post(f"/calls/{call_id}/agreements", json=payload)
    _close_report_form(call_id)


def _close_report_form(call_id: int) -> None:
    st.session_state.pop("edit_report", None)
    token = f"-{call_id}"
    for key in list(st.session_state):
        if not str(key).startswith("rep-"):
            continue
        if str(key).endswith(token) or f"-{call_id}-" in str(key):
            st.session_state.pop(key, None)
    st.rerun()


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
    phone = client_phone_input(f"edit-{card['id']}", card.get("phone") or "")
    contract_number = st.text_input(
        "Номер договора",
        value=card.get("contract_number") or "",
        placeholder="Необязательно",
    )
    save, cancel = st.columns(2)
    if save.button("Сохранить", type="primary"):
        if not name.strip() or not last_name.strip() or not phone:
            st.warning("Нужны имя, фамилия и номер: +375, код и 7 цифр.")
            return
        api_patch(
            f"/clients/{card['id']}",
            {
                "name": name.strip(),
                "last_name": last_name.strip(),
                "phone": phone,
                "contract_number": contract_number.strip(),
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
    bits = [full, client["phone"]]
    if client.get("contract_number"):
        bits.append(str(client["contract_number"]))
    return " — ".join(bits)


try:
    main()
except ApiError as exc:
    st.error(exc.message)
