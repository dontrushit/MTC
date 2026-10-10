"""Client phone field: fixed +375, operator code, and 7 digits."""

from __future__ import annotations

import streamlit as st

from app.by_phone import join_by_phone, split_by_phone


def client_phone_input(prefix: str, current: str = "") -> str | None:
    """Return +375 and 9 digits, or None while the parts are incomplete."""
    operator, local = split_by_phone(current)
    op_key = f"{prefix}-op"
    num_key = f"{prefix}-num"
    if op_key not in st.session_state:
        st.session_state[op_key] = operator
    if num_key not in st.session_state:
        st.session_state[num_key] = local
    country, code, number = st.columns([1, 1, 2])
    country.text_input("Страна", value="+375", disabled=True, key=f"{prefix}-cc")
    op = code.text_input("Код", max_chars=2, key=op_key, placeholder="29")
    local_number = number.text_input(
        "7 цифр",
        max_chars=7,
        key=num_key,
        placeholder="1234567",
    )
    return join_by_phone(op, local_number)
