"""PBX connection settings. Recording itself is switched on in the MTS cabinet."""

import streamlit as st

from app.ui.api_client import ApiError, api_get, api_post, api_put
from app.ui.theme import configure, page_heading

user = configure("Телефония")

_PRIORIY_RU = {"high": "высокий", "normal": "обычный", "low": "низкий"}
_CATEGORIES = ["КП", "встреча", "оплата"]


def _crm_block() -> None:
    st.subheader("CRM")
    if st.session_state.pop("crm_saved", False):
        st.success("Ссылка CRM сохранена.")
    data = api_get("/crm/settings") or {}
    url = st.text_input(
        "Webhook CRM",
        value=data.get("webhook_url") or "",
        placeholder="https://crm.example/hook/abcdef",
        help="Bitrix24, amoCRM или любой адрес, который принимает POST.",
    )
    token = st.text_input("Токен (необязательно)", value=data.get("token") or "")
    if st.button("Сохранить CRM", type="primary"):
        api_put("/crm/settings", {"webhook_url": url.strip(), "token": token.strip()})
        st.session_state["crm_saved"] = True
        st.rerun()


def _rules_block() -> None:
    st.subheader("Правила договорённостей")
    if st.session_state.pop("rules_saved", False):
        st.success("Правила сохранены.")
    data = api_get("/agreement-rules")
    rules = list(data.get("rules") or [])
    categories = data.get("categories") or _CATEGORIES
    priorities = data.get("priorities") or list(_PRIORIY_RU)
    rows_key = "rules-rows"
    if rows_key not in st.session_state:
        st.session_state[rows_key] = rules
    rows: list[dict] = st.session_state[rows_key]
    for index, row in enumerate(rows):
        st.session_state.setdefault(f"rule-words-{index}", ", ".join(row.get("keywords") or []))
        st.session_state.setdefault(
            f"rule-cat-{index}", row.get("category") or categories[0]
        )
        st.session_state.setdefault(f"rule-pri-{index}", row.get("priority") or "normal")
        words = st.text_input(
            "Ключевые слова (через запятую)",
            key=f"rule-words-{index}",
        )
        category, priority = st.columns(2)
        chosen = category.selectbox("Тип", categories, key=f"rule-cat-{index}")
        weight = priority.selectbox(
            "Приоритет",
            priorities,
            format_func=lambda item: _PRIORIY_RU.get(item, item),
            key=f"rule-pri-{index}",
        )
        st.session_state[rows_key][index] = {
            "keywords": [word.strip() for word in words.split(",") if word.strip()],
            "category": chosen,
            "priority": weight,
        }
        if st.button("Убрать правило", key=f"rule-drop-{index}"):
            st.session_state[rows_key].pop(index)
            for key in list(st.session_state):
                if key.startswith("rule-words-") or key.startswith("rule-cat-") or key.startswith(
                    "rule-pri-"
                ):
                    st.session_state.pop(key, None)
            st.rerun()
    if st.button("Добавить правило"):
        st.session_state[rows_key].append(
            {"keywords": [], "category": categories[0], "priority": "normal"}
        )
        st.rerun()
    defaults, save = st.columns(2)
    if defaults.button("Вернуть типовые правила"):
        api_put("/agreement-rules", {"rules": _default_rules()})
        st.session_state[rows_key] = _default_rules()
        st.rerun()
    if save.button("Сохранить правила", type="primary"):
        api_put("/agreement-rules", {"rules": list(st.session_state[rows_key])})
        st.session_state["rules_saved"] = True
        st.rerun()


def _default_rules() -> list[dict]:
    return [
        {"keywords": ["кп", "коммерческое предложение"], "category": "КП", "priority": "normal"},
        {"keywords": ["встреч", "демо", "звонок"], "category": "встреча", "priority": "high"},
        {
            "keywords": ["оплат", "счёт", "счет", "выплат", "предоплат"],
            "category": "оплата",
            "priority": "high",
        },
    ]


def _form(data: dict) -> None:
    st.text_input("Адрес для кабинета оператора", value=data["event_url"], disabled=True)
    with st.form("atc_settings"):
        recording_url = st.text_input(
            "Ссылка на запись",
            value=data.get("recording_url") or "",
            placeholder="https://сервер/recordings/{call_id}",
        )
        managers = _manager_phones(data)
        if st.form_submit_button("Сохранить", type="primary"):
            if any(not item["name"] for item in managers):
                st.warning("Нужно имя сотрудника.")
                return
            api_put(
                "/atc/settings",
                {
                    "public_url": data.get("public_url") or "",
                    "basic_user": data.get("basic_user") or "",
                    "basic_password": data.get("basic_password") or "",
                    "recording_url": recording_url.strip(),
                    "manager_id": data.get("manager_id"),
                    "managers": managers,
                },
            )
            st.session_state["atc_saved"] = True
            st.rerun()


def _manager_phones(data: dict) -> list[dict]:
    rows = list(data.get("managers") or [])
    if not rows:
        st.caption("Сначала добавьте сотрудника.")
        return []
    people = []
    for item in rows:
        name_key = f"mgr-name-{item['id']}"
        phone_key = f"mgr-phone-{item['id']}"
        if name_key not in st.session_state:
            st.session_state[name_key] = item["name"]
        if phone_key not in st.session_state:
            st.session_state[phone_key] = item.get("phone") or ""
        name = st.text_input("Сотрудник", key=name_key)
        phone = st.text_input(
            "Короткий номер в Автосекретаре",
            placeholder="Короткий номер",
            key=phone_key,
        )
        password = st.text_input(
            "Пароль для входа",
            type="password",
            placeholder="Не менять",
            key=f"mgr-pass-{item['id']}",
        )
        people.append(
            {
                "id": int(item["id"]),
                "name": name.strip(),
                "phone": phone.strip(),
                "password": password,
            }
        )
    return people


def _add_employee() -> None:
    with st.form("new_employee"):
        st.caption("Новый сотрудник")
        name = st.text_input("Имя")
        password = st.text_input("Пароль", type="password")
        phone = st.text_input("Короткий номер в Автосекретаре", placeholder="Короткий номер")
        if st.form_submit_button("Добавить"):
            if not name.strip() or len(password) < 4:
                st.warning("Нужны имя и пароль.")
                return
            api_post(
                "/managers",
                json={"name": name.strip(), "password": password, "phone": phone.strip()},
            )
            st.rerun()


try:
    if not user.get("is_supervisor"):
        page_heading("Настройка")
        st.info("Настройки меняет ответственный сотрудник.")
        st.stop()
    page_heading("Телефония")
    if st.session_state.pop("atc_saved", None):
        st.success("Сохранено.")
    _form(api_get("/atc/settings"))
    _add_employee()
    show_section = st.container()
    with show_section:
        st.subheader("CRM и правила")
        _crm_block()
        _rules_block()
except ApiError as exc:
    st.error(exc.message)
