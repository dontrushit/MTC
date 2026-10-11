"""Calendar of ready reports: month grid → day → list of calls → card."""

from datetime import date, timedelta

import streamlit as st

from app.ui.api_client import ApiError, api_get
from app.ui.labels import format_dt
from app.ui.theme import (
    agreement_actions,
    configure,
    page_heading,
    show_call_extras,
    show_call_report,
    show_consent,
    show_section,
)

user = configure("Календарь")

_MONTH_STEP = timedelta(days=1)


def _month_bounds(anchor: date) -> tuple[date, date]:
    first = anchor.replace(day=1)
    if anchor.month == 12:
        last = first.replace(year=anchor.year + 1, month=1)
    else:
        last = first.replace(year=anchor.year, month=anchor.month + 1)
    return first, last - _MONTH_STEP


def _grid(first: date, last: date) -> list[list[int]]:
    weeks: list[list[int]] = []
    row = [0] * first.weekday()
    index = first.day
    while index <= last.day:
        row.append(index)
        day = first.replace(day=index)
        if day.weekday() == 6 or index == last.day:
            weeks.append(row + [0] * (7 - len(row)))
            row = []
        index += 1
    return weeks


try:
    page_heading("Календарь", "Отчёты звонков по дням.")
    calls = [
        call
        for call in api_get("/calls")
        if str(call.get("status")) == "extracted"
    ]
    anchor = st.date_input("Месяц", value=date.today(), format="YYYY-MM")
    first, last = _month_bounds(anchor)
    ready: dict[int, list[dict]] = {}
    for call in calls:
        day = str(call.get("started_at") or "")[:10]
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            continue
        if parsed.month == anchor.month and parsed.year == anchor.year:
            ready.setdefault(parsed.day, []).append(call)

    weeks = _grid(first, last)
    for week in weeks:
        cells = st.columns(7)
        for offset, day_number in enumerate(week):
            if not day_number:
                continue
            count = len(ready.get(day_number, []))
            cells[offset].metric(str(day_number), "—" if not count else str(count))

    chosen = st.date_input(
        "День",
        value=date(anchor.year, anchor.month, min(anchor.day, last.day)),
        min_value=first,
        max_value=last,
    )
    rows = ready.get(getattr(chosen, "day", 0), [])
    show_section(f"Звонки {getattr(chosen, 'day', '')}.{anchor.month}.{anchor.year}")
    if not rows:
        st.caption("В этот день отчётных звонков нет.")
        st.stop()
    for call in rows:
        who = format_dt(call.get("started_at"))
        with st.expander(f"{who} — {call.get('report_topic') or 'тема не указана'}"):
            detail = api_get(f"/calls/{call['id']}")
            show_call_report(detail, detail.get("agreements") or [])
            show_consent(detail)
            show_call_extras(detail)
            for agreement in detail.get("agreements") or []:
                agreement_actions(agreement)
except ApiError as exc:
    st.error(exc.message)
