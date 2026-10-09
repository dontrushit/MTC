"""HTTP client for the Streamlit UI. The UI never opens the database."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class ApiError(Exception):
    """User-facing API or network failure."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"Ошибка API ({response.status_code})"
    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(part) for part in item.get("loc", []) if part != "body")
                msg = str(item.get("msg", "")).strip()
                parts.append(f"{loc}: {msg}" if loc and msg else msg or str(item))
            else:
                parts.append(str(item))
        joined = "; ".join(part for part in parts if part)
        return joined or f"Ошибка API ({response.status_code})"
    return str(detail)


def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    url = settings.API_URL.rstrip("/") + path
    try:
        with httpx.Client(timeout=60) as client:
            response = client.request(method, url, **kwargs)
    except httpx.ConnectError:
        raise ApiError("Не удалось подключиться к API. Запустите сервер на порту 8000.") from None
    except httpx.TimeoutException:
        raise ApiError("API не ответил вовремя.") from None
    except httpx.HTTPError as exc:
        raise ApiError(f"Ошибка сети: {exc}") from None
    if response.status_code >= 400:
        raise ApiError(_detail(response))
    return response


def api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    query = None
    if params:
        query = {key: value for key, value in params.items() if value is not None and value != ""}
    return _request("GET", path, params=query).json()


def api_post(path: str, **kwargs: Any) -> Any:
    response = _request("POST", path, **kwargs)
    if not response.content:
        return None
    return response.json()


def api_patch(path: str, payload: dict[str, Any]) -> Any:
    return _request("PATCH", path, json=payload).json()


def api_delete(path: str) -> None:
    _request("DELETE", path)


def api_get_bytes(path: str) -> tuple[bytes, str]:
    response = _request("GET", path)
    media = response.headers.get("content-type", "application/octet-stream").split(";")[0]
    return response.content, media
