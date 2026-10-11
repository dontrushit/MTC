"""Supervisor dashboard: KPI of the team, timeliness, and types of agreements."""

import streamlit as st

from app.ui.api_client import ApiError, api_get
from app.ui.labels import agreement_status_ru
from app.ui.theme import configure, page_heading, show_metrics, show_section

user = configure("Команда")


def _overdue_rows(rows: list[dict], clients: dict[int, str]) -> list[dict]:
    table = []
    for row in rows:
        client_name = clients.get(int(row.get("client_id") or 0), "")
        due = row.get("due_date") or row.get("due_text") or "срок не обговорён"
        table.append(
            {
                "Контакт": client_name,
                "Что сделать": row.get("action") or "",
                "Кто": "пользователь" if row.get("responsible") == "manager" else "контакт",
                "Срок": str(due)[:10],
                "Статус": agreement_status_ru(str(row.get("status") or "")),
            }
        )
    return table


def _client_names(rows: list[dict]) -> dict[int, str]:
    names: dict[int, str] = {}
    for row in rows:
        client_id = int(row.get("client_id") or 0)
        if client_id and client_id not in names:
            try:
                card = api_get(f"/clients/{client_id}")
            except ApiError:
                continue
            names[client_id] = " ".join(
                part for part in (card.get("name"), card.get("last_name")) if part
            )
    return names


try:
    page_heading("Команда", "Что происходит с договорённостями команды.")
    if not user.get("is_supervisor"):
        st.info("Дашборд видит ответственный сотрудник.")
        st.stop()
    overview = api_get("/stats/agreements")
    on_time = overview.get("done_on_time")
    show_metrics(
        [
            (str(overview.get("open") or 0), "открыто", ""),
            (str(overview.get("overdue") or 0), "просрочено", "red"),
            (str(overview.get("done") or 0), "выполнено", "green"),
            ("—" if on_time is None else f"{on_time}%", "в срок", ""),
        ]
    )
    show_section("По типам договорённостей")
    categories = list(overview.get("categories") or [])
    if categories:
        st.dataframe(
            [
                {
                    "Тип": item.get("category") or "(без типа)",
                    "Всего": item.get("total") or 0,
                    "Открыто": item.get("open") or 0,
                    "Просрочено": item.get("overdue") or 0,
                    "Выполнено": item.get("done") or 0,
                }
                for item in categories
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("Договорённостей ещё нет.")

    show_section("Сводка по пользователям")
    stats = list(api_get("/stats/managers"))
    if stats:
        st.dataframe(
            [
                {
                    "Пользователь": item.get("name") or "",
                    "Открыто": item.get("open") or 0,
                    "Просрочено": item.get("overdue") or 0,
                    "Выполнено": item.get("done") or 0,
                "В срок": "—"
                if item.get("done_on_time") is None
                else f"{item['done_on_time']}%",
                }
                for item in stats
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("Сотрудников пока нет.")

    show_section("Просроченные договорённости")
    overdue = list(api_get("/agreements", params={"status": "overdue"}))
    if overdue:
        st.dataframe(
            _overdue_rows(overdue, _client_names(overdue)),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("Просроченных нет.")
except ApiError as exc:
    st.error(exc.message)
