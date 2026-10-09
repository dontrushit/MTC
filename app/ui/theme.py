"""MTS-inspired chrome for the Streamlit UI. Pages talk to the API only."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import streamlit as st

from app.ui.labels import agreement_status_ru, format_clock, responsible_ru

_CSS = Path(__file__).with_name("mts.css")

_NAV = (
    ("", "Звонок"),
    ("Клиенты", "Клиенты"),
)

_QUICK = (
    ("Загрузка", "Загрузить запись", "Аудио — расшифровка начнётся сама", "doc"),
    ("Клиенты", "Карточка клиента", "Имя, компания и открытые обязательства", "person"),
    ("Клиенты", "История звонков", "Диалог, запись и цитаты", "sim"),
    ("Руководитель", "Контроль сроков", "Просроченные видны руководителю", "check"),
)

_ICONS = (
    ("Загрузка", "Загрузка", "doc", False),
    ("Клиенты", "Клиенты", "person", False),
    ("Договорённости", "Договорённости", "check", True),
    ("Клиенты", "Диалог", "chat", False),
    ("Договорённости", "Сроки", "clock", False),
    ("Руководитель", "Руководитель", "chart", False),
)

_AGREEMENT_TONE = {
    "open": "blue",
    "overdue": "red",
    "done": "green",
    "cancelled": "muted",
}

_PIN = "<span class='mts-pin' aria-hidden='true'></span>"
_SEARCH = "<span class='mts-glass' aria-hidden='true'></span>"
_BARS = "<span class='mts-bars' aria-hidden='true'><i></i><i></i><i></i></span>"

_STEPS = (
    ("01", "Менеджер и клиент", "Выберите карточку или создайте новую"),
    ("02", "Кнопка записи", "Начните в момент звонка и остановите в конце"),
    ("03", "Расшифровка", "Статус обновляется, пока идёт обработка"),
    ("04", "Отчёт", "Диалог, срок, ответственный и цитата"),
)

_ART = (
    "<div class='mts-art' aria-hidden='true'>"
    "<div class='mts-ring'></div>"
    "<div class='mts-coin mts-coin-pale'><span>₽</span></div>"
    "<div class='mts-coin mts-coin-red'><span>СРОК</span></div>"
    "<div class='mts-coin mts-coin-blue'><span>«»</span></div>"
    "</div>"
)


def configure(title: str, *, with_chrome: bool = True) -> None:
    st.set_page_config(
        page_title=title,
        page_icon="🔴",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.html(_CSS)
    _sync_notice()
    if with_chrome:
        st.html(page_shell())


def show_home() -> None:
    st.html(page_shell(_home_body(), notice=True))


def page_heading(title: str, subtitle: str = "") -> None:
    sub = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    st.html(f"<header class='mts-page-head'><h1>{html.escape(title)}</h1>{sub}</header>")


def show_section(title: str) -> None:
    st.html(f"<h2 class='mts-h2'>{html.escape(title)}</h2>")


def show_client(card: dict) -> None:
    first = html.escape(str(card.get("name") or "—"))
    last = html.escape(str(card.get("last_name") or "—"))
    phone = html.escape(str(card.get("phone") or "—"))
    st.html(
        "<dl class='mts-profile'>"
        f"<div><dt>Имя</dt><dd>{first}</dd></div>"
        f"<div><dt>Фамилия</dt><dd>{last}</dd></div>"
        f"<div><dt>Номер</dt><dd>{phone}</dd></div>"
        "</dl>"
    )


def show_agreement(agreement: dict) -> None:
    status = str(agreement.get("status") or "")
    tone = _AGREEMENT_TONE.get(status, "muted")
    bits = [responsible_ru(str(agreement.get("responsible") or ""))]
    if agreement.get("due_date"):
        bits.append(f"срок {_ru_date(str(agreement['due_date']))}")
    if agreement.get("amount"):
        bits.append(str(agreement["amount"]))
    conditions = str(agreement.get("conditions") or "")
    quote = str(agreement.get("quote") or "")
    cond_html = f"<p class='mts-meta'>{html.escape(conditions)}</p>" if conditions else ""
    quote_html = f"<p class='mts-quote'>«{html.escape(quote)}»</p>" if quote else ""
    st.html(
        f"<article class='mts-agree mts-agree-{html.escape(status)}'>"
        "<div class='mts-agree-top'>"
        f"<h3>{html.escape(str(agreement.get('action') or ''))}</h3>"
        f"<span class='mts-pill mts-pill-{tone}'>{html.escape(agreement_status_ru(status))}</span>"
        "</div>"
        f"<p class='mts-meta'>{html.escape(' · '.join(bits))}</p>"
        f"{cond_html}{quote_html}</article>"
    )


def show_call_report(call: dict, agreements: list[dict]) -> None:
    """Short structured report: topic, one line of context, agreements, open point."""
    report = _report_dict(call)
    blocks: list[str] = []
    _section(blocks, "Тема", report.get("topic", ""))
    _section(blocks, "Кратко", report.get("brief", ""))
    blocks.append("<p class='mts-report-label'>Договорённости</p>")
    blocks.append(_agreement_block(agreements))
    _section(blocks, "Не решено", report.get("unresolved", ""))
    st.html(f"<section class='mts-report'>{''.join(blocks)}</section>")


_AUDIO_FORMATS = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


def show_call_extras(call: dict) -> None:
    """Optional dialog and audio player. The player can seek."""
    from app.ui.api_client import ApiError, api_get_bytes

    call_id = int(call["id"])
    dialog_key = f"dialog-open-{call_id}"
    audio_key = f"audio-open-{call_id}"
    dialog_on = bool(st.session_state.get(dialog_key))
    audio_on = bool(st.session_state.get(audio_key))
    left, right = st.columns(2)
    dialog_label = "Скрыть диалог" if dialog_on else "Диалог"
    audio_label = "Скрыть запись" if audio_on else "Прослушать"
    if left.button(dialog_label, key=f"dialog-btn-{call_id}"):
        st.session_state[dialog_key] = not dialog_on
        st.rerun()
    if right.button(audio_label, key=f"audio-btn-{call_id}"):
        st.session_state[audio_key] = not audio_on
        st.rerun()
    if dialog_on:
        show_dialog(list(call.get("utterances") or []))
    if audio_on:
        try:
            data, media = api_get_bytes(f"/calls/{call_id}/audio")
        except ApiError as exc:
            st.warning(exc.message)
        else:
            st.audio(
                data,
                format=_audio_format(str(call.get("audio_path") or ""), media),
            )
            st.caption("Ползунок перематывает запись.")


def _audio_format(path: str, media: str) -> str:
    if media.startswith("audio/"):
        return media
    return _AUDIO_FORMATS.get(Path(path).suffix.lower(), "audio/wav")


def _report_dict(call: dict) -> dict:
    raw = str(call.get("report_json") or "").strip()
    data: dict = {}
    if raw:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    if not str(data.get("topic") or "").strip():
        data["topic"] = call.get("report_topic") or ""
    if "brief" not in data and str(call.get("report_summary") or "").strip():
        summary = str(call.get("report_summary") or "").strip()
        long_fields = ("client_request", "manager_response", "outcome", "facts")
        if not any(data.get(name) for name in long_fields):
            data["brief"] = summary
    return data


def _section(blocks: list[str], title: str, text: object) -> None:
    body = str(text or "").strip()
    if not body:
        return
    blocks.append(
        f"<p class='mts-report-label'>{html.escape(title)}</p>"
        f"<p class='mts-report-text'>{html.escape(body)}</p>"
    )


def _agreement_block(agreements: list[dict]) -> str:
    if not agreements:
        return "<p class='mts-report-empty'>В этом разговоре договорённостей нет.</p>"
    items = []
    for index, agreement in enumerate(agreements, start=1):
        bits = [responsible_ru(str(agreement.get("responsible") or ""))]
        if agreement.get("due_date"):
            bits.append(_ru_date(str(agreement["due_date"])))
        elif agreement.get("due_text"):
            bits.append(str(agreement["due_text"]))
        if agreement.get("amount"):
            bits.append(str(agreement["amount"]))
        conditions = str(agreement.get("conditions") or "").strip()
        extra = ""
        if conditions:
            extra += f"<p class='mts-report-note'>{html.escape(conditions)}</p>"
        items.append(
            "<li class='mts-report-item'>"
            f"<b>{index}. {html.escape(str(agreement.get('action') or ''))}</b>"
            f"<span>{html.escape(' · '.join(bit for bit in bits if bit))}</span>"
            f"{extra}</li>"
        )
    return f"<ol class='mts-report-list'>{''.join(items)}</ol>"


def show_dialog(utterances: list[dict]) -> None:
    if not utterances:
        st.caption("Реплик пока нет.")
        return
    chunks: list[str] = []
    for utterance in utterances:
        is_manager = utterance["speaker"] == "manager"
        who = "Менеджер" if is_manager else "Клиент"
        kind = "manager" if is_manager else "client"
        stamp = f"{format_clock(utterance['start_sec'])}–{format_clock(utterance['end_sec'])}"
        chunks.append(
            f"<div class='mts-bubble mts-bubble-{kind}'>"
            f"<b>{who}</b><time>{html.escape(stamp)}</time>"
            f"<div>{html.escape(str(utterance['text']))}</div></div>"
        )
    st.html(f"<div class='mts-dialog'>{''.join(chunks)}</div>")


def show_metrics(items: list[tuple[str, str, str]]) -> None:
    cells = []
    for value, label, tone in items:
        extra = f" mts-metric-{tone}" if tone else ""
        cells.append(
            f"<div class='mts-metric{extra}'><b>{html.escape(value)}</b>"
            f"<span>{html.escape(label)}</span></div>"
        )
    st.html(f"<div class='mts-metrics'>{''.join(cells)}</div>")


def upload_aside() -> str:
    items = [
        "<li><b>"
        + num
        + "</b><div><strong>"
        + title
        + "</strong><span>"
        + text
        + "</span></div></li>"
        for num, title, text in _STEPS
    ]
    return (
        "<aside class='mts-aside'><h2>Как проходит загрузка</h2>"
        f"<ol class='mts-steps'>{''.join(items)}</ol></aside>"
    )


def status_card(call_id: int, status: str, status_label: str, started: str) -> str:
    safe_status = html.escape(status)
    return (
        f"<div class='mts-status mts-status-{safe_status}'>"
        f"<strong>Звонок #{call_id}</strong>"
        f"<span>{html.escape(status_label)} · {html.escape(started)}</span></div>"
    )


def page_shell(body: str = "", *, notice: bool = False) -> str:
    bar = ""
    if notice and not st.session_state.get("mts_notice_ok"):
        bar = _notice(bool(st.session_state.get("mts_notice_more")))
    return f"{_header()}{body}{bar}"


def _sync_notice() -> None:
    flag = st.query_params.get("notice")
    if flag == "ok":
        st.session_state["mts_notice_ok"] = True
    elif flag == "more":
        st.session_state["mts_notice_more"] = True
    if flag in ("ok", "more") and "notice" in st.query_params:
        del st.query_params["notice"]


def _current_slug() -> str:
    try:
        raw = st.context.url or ""
    except Exception:
        return ""
    path = unquote(urlparse(raw).path).strip("/")
    return path.split("/")[-1] if path else ""


def _header() -> str:
    current = _current_slug()
    links = []
    for slug, label in _NAV:
        href = "/" if slug == "" else f"/{slug}"
        active = " class='is-active'" if current == slug else ""
        links.append(f"<a href='{href}'{active}>{html.escape(label)}</a>")
    return (
        "<div class='mts-chrome'>"
        "<div class='mts-bar'>"
        f"<nav class='mts-menu'>{''.join(links)}</nav>"
        "</div></div>"
    )


def _notice(expanded: bool) -> str:
    extra = (
        "<p class='mts-notice-more'>Речь распознаётся локально, договорённость сверяется "
        "с цитатой, срок считает само приложение.</p>"
        if expanded
        else ""
    )
    return (
        "<div class='mts-notice-slot'><div class='mts-notice'>"
        "<div class='mts-notice-copy'>"
        "<p>Записи и расшифровки остаются "
        "<a class='mts-a' href='?notice=more'>на этом компьютере</a>.</p>"
        f"{extra}</div>"
        "<a class='mts-btn mts-btn-ghost' href='?notice=more'>Подробнее</a>"
        "<a class='mts-btn mts-btn-red' href='?notice=ok'>Принять</a>"
        "</div></div>"
    )


def _home_body() -> str:
    quick = "".join(
        "<a href='/"
        + slug
        + "'><span class='mts-quick-ico'>"
        + _ico(icon)
        + "</span><span><strong>"
        + title
        + "</strong><span class='mts-quick-text'>"
        + text
        + "</span></span></a>"
        for slug, title, text, icon in _QUICK
    )
    icons = []
    for slug, label, icon, bonus in _ICONS:
        badge = "<span class='mts-bonus'>+ цитата</span>" if bonus else ""
        icons.append(
            f"<a class='mts-icon' href='/{slug}'>"
            f"<span class='mts-icon-box'>{badge}{_ico(icon)}</span>{label}</a>"
        )
    return (
        "<section class='mts-home'><div class='mts-hero-row'><div class='mts-hero'>"
        "<div class='mts-hero-copy'><h1>Фиксируйте договорённости<br>из каждого звонка</h1>"
        "<div class='mts-kicker'>Срок, ответственный и цитата</div><br>"
        "<a class='mts-btn mts-btn-red mts-btn-lg' href='/Загрузка'>Загрузить звонок</a>"
        f"</div>{_ART}</div><div class='mts-quick'>{quick}</div></div>"
        f"<nav class='mts-icons'>{''.join(icons)}</nav></section>"
    )


def _ico(name: str) -> str:
    if name == "chart":
        inner = "<i></i><b></b><em></em>"
    else:
        inner = ""
    return f"<span class='ico ico-{name}' aria-hidden='true'>{inner}</span>"


def _ru_date(value: str) -> str:
    parts = value[:10].split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        year, month, day = parts
        return f"{day}.{month}.{year}"
    return value
