"""Client search and card."""

import html
from pathlib import Path

import streamlit as st

from app.ui.api_client import ApiError, api_get, api_get_bytes
from app.ui.labels import (
    agreement_status_ru,
    call_status_ru,
    format_clock,
    format_dt,
    responsible_ru,
)

st.set_page_config(page_title="Клиенты", page_icon="👤", layout="wide")

_AUDIO_FORMATS = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


def _audio_format(path: str, media: str) -> str:
    if media.startswith("audio/"):
        return media
    return _AUDIO_FORMATS.get(Path(path).suffix.lower(), "audio/wav")


def _agreement_block(agreement: dict) -> None:
    overdue = agreement["status"] == "overdue"
    title = agreement["action"]
    if overdue:
        st.markdown(f":red[**{title}**] — :red[{agreement_status_ru(agreement['status'])}]")
    else:
        st.markdown(f"**{title}** — {agreement_status_ru(agreement['status'])}")
    bits = [responsible_ru(agreement["responsible"])]
    if agreement.get("due_date"):
        bits.append(f"срок {agreement['due_date']}")
    if agreement.get("amount"):
        bits.append(str(agreement["amount"]))
    st.caption(" · ".join(bits))
    if agreement.get("conditions"):
        st.caption(agreement["conditions"])
    quote = agreement.get("quote") or ""
    if quote:
        st.caption(f"«{quote}»")


def main() -> None:
    st.title("Клиенты")
    query = st.text_input("Поиск по имени, телефону или компании")
    clients = api_get("/clients", params={"q": query.strip()})
    if not clients:
        st.info("Ничего не найдено.")
        return

    client_id = st.selectbox(
        "Клиент",
        options=[item["id"] for item in clients],
        format_func=lambda item_id: _label(clients, item_id),
    )
    card = api_get(f"/clients/{client_id}")
    managers = {item["id"]: item["name"] for item in api_get("/managers")}

    st.subheader(card["name"])
    company = card.get("company") or "—"
    st.write(f"Телефон: {card['phone']} · Компания: {company}")

    st.subheader("Открытые договорённости")
    active = [
        item for item in card["agreements"] if item["status"] in ("open", "overdue")
    ]
    if not active:
        st.caption("Нет открытых договорённостей.")
    else:
        for agreement in active:
            _agreement_block(agreement)

    st.subheader("История звонков")
    if not card["calls"]:
        st.caption("Звонков пока нет.")
        return
    st.caption("Менеджер — голубой, клиент — зелёный.")
    for call in card["calls"]:
        manager_name = managers.get(call["manager_id"], "—")
        title = (
            f"{format_dt(call['started_at'])} — {manager_name} — {call_status_ru(call['status'])}"
        )
        with st.expander(title):
            if call["status"] == "error" and call.get("error_message"):
                st.error(call["error_message"])
            _render_call(call["id"])


def _render_call(call_id: int) -> None:
    detail = api_get(f"/calls/{call_id}")
    try:
        audio, media = api_get_bytes(f"/calls/{call_id}/audio")
    except ApiError as exc:
        st.warning(exc.message)
    else:
        st.audio(audio, format=_audio_format(detail["audio_path"], media))

    if not detail["utterances"]:
        st.caption("Реплик пока нет.")
    for utterance in detail["utterances"]:
        is_manager = utterance["speaker"] == "manager"
        who = "Менеджер" if is_manager else "Клиент"
        bg = "#dbeafe" if is_manager else "#dcfce7"
        stamp = f"{format_clock(utterance['start_sec'])}–{format_clock(utterance['end_sec'])}"
        text = html.escape(utterance["text"])
        st.markdown(
            (
                f"<div style='background:{bg};padding:0.55rem 0.8rem;"
                "border-radius:8px;margin-bottom:0.35rem'>"
                f"<b>{who}</b> <span style='color:#64748b'>{stamp}</span><br>{text}</div>"
            ),
            unsafe_allow_html=True,
        )

    if detail["agreements"]:
        st.markdown("**Договорённости звонка**")
        for agreement in detail["agreements"]:
            _agreement_block(agreement)


def _label(clients: list[dict], client_id: int) -> str:
    client = next(item for item in clients if item["id"] == client_id)
    company = f" ({client['company']})" if client.get("company") else ""
    return f"{client['name']}{company} — {client['phone']}"


try:
    main()
except ApiError as exc:
    st.error(exc.message)
