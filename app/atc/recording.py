"""Download a call recording. This is the only piece that needs the MTS file URL."""

from __future__ import annotations

import base64
import logging
import urllib.error
import urllib.request

from app.atc.options import load_options
from app.db.session import get_session

logger = logging.getLogger(__name__)


def fetch_recording(external_id: str) -> bytes | None:
    """GET the recording URL with {call_id} filled in. An empty URL skips the download.

    The address is saved on the settings screen. If the MTS API is not a simple GET,
    change only this function.
    """
    with get_session() as session:
        options = load_options(session)
    template = options.recording_url
    if not template:
        return None
    url = template.format(call_id=external_id)
    request = urllib.request.Request(url)
    user = options.basic_user
    password = options.basic_password
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
