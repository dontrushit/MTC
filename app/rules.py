"""Agreement templates: rules that turn keywords into a category and a priority.

Rules are stored in the `app_settings` table as JSON, so a supervisor can edit
them on the settings screen without touching the code.
"""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.db.models import AppSetting

RULES_KEY = "agreement_rules"
CRM_URL_KEY = "crm_webhook_url"
CRM_TOKEN_KEY = "crm_token"

CATEGORIES: tuple[str, ...] = ("КП", "встреча", "оплата", "другое")
PRIORITIES: tuple[str, ...] = ("high", "normal", "low")

PRIORITY_RU = {
    "high": "высокий",
    "normal": "обычный",
    "low": "низкий",
}

DEFAULT_RULES: list[dict] = [
    {
        "keywords": ["кп", "коммерческое предложение"],
        "category": "КП",
        "priority": "normal",
    },
    {
        "keywords": ["встреч", "демо", "звонок"],
        "category": "встреча",
        "priority": "high",
    },
    {
        "keywords": ["оплат", "счёт", "счет", "выплат", "предоплат"],
        "category": "оплата",
        "priority": "high",
    },
]


def load_rules(session: Session) -> list[dict]:
    row = session.get(AppSetting, RULES_KEY)
    if row is None:
        return [dict(item) for item in DEFAULT_RULES]
    try:
        data = json.loads(row.value)
    except json.JSONDecodeError:
        return [dict(item) for item in DEFAULT_RULES]
    if not isinstance(data, list):
        return [dict(item) for item in DEFAULT_RULES]
    return [item for item in data if _valid(item)]


def save_rules(session: Session, rules: list[dict]) -> list[dict]:
    cleaned = [_clean(item) for item in rules if _valid(item)]
    row = session.get(AppSetting, RULES_KEY)
    if row is None:
        row = AppSetting(key=RULES_KEY, value="")
        session.add(row)
    row.value = json.dumps(cleaned, ensure_ascii=False)
    return cleaned


def classify(text: str, rules: list[dict], *, default_category: str = "") -> tuple[str, str]:
    """Return (category, priority) for an action text. First matching rule wins."""
    needle = _normalize(text)
    for rule in rules:
        keywords = [str(item) for item in rule.get("keywords") or []]
        if any(_normalize(word) in needle for word in keywords if word.strip()):
            category = str(rule.get("category") or default_category)
            priority = str(rule.get("priority") or "normal")
            return category, priority
    return default_category, "normal"


def _normalize(text: str) -> str:
    lowered = (text or "").casefold()
    return re.sub(r"\s+", " ", lowered).strip()


def _clean(item: dict) -> dict:
    keywords = [str(word).strip() for word in item.get("keywords") or []]
    return {
        "keywords": [word for word in keywords if word],
        "category": str(item.get("category") or "").strip(),
        "priority": str(item.get("priority") or "normal").strip(),
    }


def _valid(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    keywords = [word for word in item.get("keywords") or [] if str(word).strip()]
    return bool(keywords)


def list_rules(session: Session) -> list[dict]:
    """The stored rules or the defaults, ready for JSON output."""
    return load_rules(session)


def rules_from_payload(session: Session, payload: list[dict]) -> list[dict]:
    """Validate a list posted from the UI and store it."""
    parsed: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        keywords = item.get("keywords")
        if not isinstance(keywords, list) or not any(
            str(word).strip() for word in keywords
        ):
            continue
        category = str(item.get("category") or "").strip()
        if category and category not in CATEGORIES:
            raise ValueError(f"Неизвестный тип: {category}")
        priority = str(item.get("priority") or "normal").strip()
        if priority not in PRIORITIES:
            raise ValueError(f"Неизвестный приоритет: {priority}")
        parsed.append(
            {
                "keywords": [str(word).strip() for word in keywords if str(word).strip()],
                "category": category,
                "priority": priority,
            }
        )
    return save_rules(session, parsed)


def priority_rank(value: str) -> int:
    """Lower ranks first: overdue staff care about 'high' before 'normal'."""
    order = {"high": 0, "normal": 1, "low": 2}
    return order.get(value, 1)
