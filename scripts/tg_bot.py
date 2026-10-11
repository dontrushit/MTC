#!/usr/bin/env python3
"""Standalone Telegram bot: /start <token> binds a chat, /stop unbinds.

Long polling (no webhook), stdlib only. The token comes from .env:
TELEGRAM_BOT_TOKEN. Without it the bot exits silently — the rest of the
project keeps working. Run: python scripts/tg_bot.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db.models import Manager  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.telegram import TELEGRAM_API, consume_token  # noqa: E402

API = TELEGRAM_API
POLL = 30.0


def log(message: str) -> None:
    print(f"[tg_bot] {time.strftime('%H:%M:%S')} {message}", flush=True)


def call_api(token: str, method: str, params: dict) -> dict | None:
    body = json.dumps(params).encode("utf-8")
    request = urllib.request.Request(
        f"{API}/bot{token}/{method}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=POLL + 10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log(f"api {method}: {exc}")
        return None
    return payload if isinstance(payload, dict) else None


def reply(token: str, chat_id: str, text: str) -> None:
    call_api(token, "sendMessage", {"chat_id": chat_id, "text": text})


def handle_update(token: str, update: dict) -> None:
    message = update.get("message") or {}
    text = str(message.get("text") or "").strip()
    chat_id = str(message.get("chat", {}).get("id") or "").strip()
    if not chat_id:
        return
    with get_session() as session:
        if text.startswith("/start"):
            raw = text[len("/start"):].strip()
            if not raw:
                reply(
                    token,
                    chat_id,
                    "Нужен одноразовый токен из приложения: карточка «Звонок» → "
                    "«Подключить Telegram».",
                )
                return
            manager = consume_token(session, raw)
            if manager is None:
                reply(token, chat_id, "Ссылка не действует или истекла. Сделайте новую.")
                return
            manager.telegram_chat_id = chat_id
            reply(token, chat_id, f"Подключено. Уведомления придут как {manager.name}.")
            session.commit()
            log(f"bind: {manager.name} <- {chat_id}")
            return
        if text.startswith("/stop"):
            matched = list(session.scalars(
                select(Manager).where(Manager.telegram_chat_id == chat_id)
            ).all())
            for manager in matched:
                manager.telegram_chat_id = None
            if matched:
                reply(token, chat_id, "Отключено.")
                session.commit()
                log(f"unbind chat {chat_id}")
            else:
                reply(token, chat_id, "Этот чат не был подключён.")
            return
        reply(token, chat_id, "Бот принимает /start <токен> и /stop.")


def main() -> int:
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    if not token:
        log("TELEGRAM_BOT_TOKEN не задан — бот выключен.")
        return 0
    offset = 0
    log("long polling запущен")
    while True:
        payload = call_api(token, "getUpdates", {"timeout": int(POLL), "offset": offset})
        if payload is None:
            time.sleep(5)
            continue
        for update in payload.get("result") or []:
            offset = int(update.get("update_id") or 0) + 1
            try:
                handle_update(token, update)
            except Exception as exc:  # noqa: BLE001
                log(f"update ошибка: {exc}")


if __name__ == "__main__":
    sys.exit(main())
