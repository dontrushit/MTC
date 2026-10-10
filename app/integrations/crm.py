"""One CRM webhook for agreements. Bitrix24, amoCRM, or any other endpoint."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def send_to_crm(
    url: str,
    payload: dict,
    *,
    token: str = "",
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """POST the agreement to the CRM. Returns (sent, message)."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token.strip():
        headers["X-CRM-Token"] = token.strip()
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            status = response.status
    except urllib.error.HTTPError as exc:
        return False, f"CRM ответила {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"Не удалось связаться с CRM: {reason}"
    return True, f"CRM приняла задачу ({status})"


def payload_for(
    agreement: dict,
    *,
    client_name: str,
    phone: str,
) -> dict:
    """The JSON the CRM receives. `agreement` comes from AgreementOut.model_dump."""
    due = agreement.get("due_date")
    return {
        "agreement_id": agreement.get("id"),
        "call_id": agreement.get("call_id"),
        "client_id": agreement.get("client_id"),
        "client_name": client_name,
        "phone": phone,
        "action": agreement.get("action"),
        "responsible": str(agreement.get("responsible") or ""),
        "due_date": due,
        "due_text": agreement.get("due_text") or "",
        "amount": agreement.get("amount"),
        "conditions": agreement.get("conditions"),
        "quote": agreement.get("quote") or "",
        "category": agreement.get("category") or "",
        "priority": agreement.get("priority") or "normal",
        "status": str(agreement.get("status") or ""),
    }
