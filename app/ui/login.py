"""Sign-in screen. The first visit asks for a password."""

from __future__ import annotations

import streamlit as st

from app.ui.api_client import ApiError, api_get, api_post
from app.ui.theme import page_heading

_COOKIE = "mtc_token"
_TWO_WEEKS = 60 * 60 * 24 * 14


def ensure_user() -> dict:
    if st.session_state.get("auth_clear"):
        _write_cookie("")
        if _cookie_token():
            _screen()
            st.stop()
        st.session_state.pop("auth_clear", None)
    token = str(st.session_state.get("auth_token") or "") or _cookie_token()
    if token:
        st.session_state["auth_token"] = token
        try:
            user = api_get("/auth/me")
        except ApiError:
            st.session_state.pop("auth_token", None)
            st.session_state["auth_clear"] = True
        else:
            st.session_state["auth_user"] = user
            _write_cookie(token)
            return user
    _screen()
    st.stop()
    return {}


def logout() -> None:
    try:
        api_post("/auth/logout")
    except ApiError:
        pass
    st.session_state.pop("auth_token", None)
    st.session_state.pop("auth_user", None)
    st.session_state["auth_clear"] = True
    st.rerun()


def _cookie_token() -> str:
    try:
        return str(st.context.cookies.get(_COOKIE) or "")
    except Exception:
        return ""


def _write_cookie(token: str) -> None:
    if token:
        assignment = f"{_COOKIE}={token}; Path=/; Max-Age={_TWO_WEEKS}; SameSite=Lax"
    else:
        assignment = f"{_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax"
    st.html(
        f"<script>document.cookie = {assignment!r};</script>",
        unsafe_allow_javascript=True,
    )


def _screen() -> None:
    try:
        status = api_get("/auth/status")
    except ApiError as exc:
        st.error(exc.message)
        return
    if status.get("needs_setup"):
        _setup(status.get("managers") or [])
        return
    _login(status.get("managers") or [])


def _setup(managers: list[dict]) -> None:
    page_heading(
        "Вход",
        "Выберите своё имя и придумайте пароль. Каждый сотрудник входит под своим.",
    )
    with st.form("setup"):
        manager_id = None
        name = ""
        if managers:
            labels = {int(item["id"]): item["name"] for item in managers}
            manager_id = st.selectbox(
                "Ваше имя",
                options=list(labels),
                format_func=lambda item: labels[item],
                index=None,
                placeholder="Выберите себя",
            )
        else:
            name = st.text_input("Ваше имя")
        password = st.text_input("Пароль", type="password")
        again = st.text_input("Пароль ещё раз", type="password")
        if st.form_submit_button("Сохранить и войти", type="primary"):
            if managers and manager_id is None:
                st.warning("Выберите своё имя.")
                return
            if password != again:
                st.warning("Пароли не совпадают.")
                return
            if len(password) < 4:
                st.warning("Пароль слишком короткий.")
                return
            body: dict = {"password": password}
            if manager_id is not None:
                body["manager_id"] = int(manager_id)
            else:
                body["name"] = name.strip()
            _enter("/auth/setup", body)


def _login(managers: list[dict]) -> None:
    page_heading("Вход", "Выберите своё имя. У каждого свой пароль.")
    with st.form("login"):
        if managers:
            names = [item["name"] for item in managers]
            name = st.selectbox("Ваше имя", options=names, index=None, placeholder="Выберите себя")
        else:
            name = st.text_input("Ваше имя")
        password = st.text_input("Пароль", type="password")
        if st.form_submit_button("Войти", type="primary"):
            if not name:
                st.warning("Выберите своё имя.")
                return
            _enter("/auth/login", {"name": str(name).strip(), "password": password})


def _enter(path: str, body: dict) -> None:
    try:
        user = api_post(path, json=body)
    except ApiError as exc:
        st.error(exc.message)
        return
    st.session_state["auth_token"] = user["token"]
    st.session_state["auth_user"] = user
    st.rerun()
