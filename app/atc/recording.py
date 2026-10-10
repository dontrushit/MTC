"""Download a call recording. This is the only piece that needs the MTS file URL."""

from __future__ import annotations

import base64
import logging
import urllib.error
import urllib.request

from app.config import settings

logger = logging.getLogger(__name__)


def fetch_recording(external_id: str) -> bytes | None:
    """GET ATC_RECORDING_URL with {call_id} filled in. Empty setting means not yet.

    When MTS gives the real recording URL and API key, put the URL in
    ATC_RECORDING_URL. If their API is not a simple GET, change only this function.
    """
    template = settings.ATC_RECORDING_URL.strip()
    if not template:
        return None
    url = template.format(call_id=external_id)
    request = urllib.request.Request(url)
    user = settings.ATC_BASIC_USER
    password = settings.ATC_BASIC_PASSWORD
    if user or password:
        token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        logger.exception("ATC recording download failed for call %s", external_id)
        return None
    return payload or None
