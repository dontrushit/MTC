#!/usr/bin/env python3
"""Environment readiness report for MTC (does not exit on missing components)."""

from __future__ import annotations

import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from sys import version_info

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def check_python() -> tuple[bool, str]:
    ok = version_info >= (3, 11)
    ver = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
    if ok:
        return True, f"Python {ver}"
    return False, f"Python {ver} (need >= 3.11). Install Python 3.11+ and recreate .venv."


def check_ffmpeg() -> tuple[bool, str]:
    path = shutil.which("ffmpeg")
    if path:
        return True, f"ffmpeg found at {path}"
    return False, "ffmpeg not in PATH. Install: brew install ffmpeg"


def _ollama_has_model(required: str, available: list[str]) -> bool:
    if required in available:
        return True
    base = required.split(":")[0]
    for name in available:
        if name == required or name.startswith(f"{required}:"):
            return True
        if name.split(":")[0] == base and ":" in required:
            tag = required.split(":", 1)[1]
            if name.endswith(f":{tag}") or f":{tag}" in name:
                return True
    return False


def check_ollama() -> tuple[bool, str]:
    url = settings.OLLAMA_URL.rstrip("/")
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        return False, f"Ollama unreachable at {url}: {exc}. Run: ollama serve"
    except json.JSONDecodeError:
        return False, f"Ollama at {url} returned invalid JSON. Check OLLAMA_URL in .env"

    available = [m.get("name", "") for m in body.get("models", []) if m.get("name")]
    missing = [
        m
        for m in (settings.OLLAMA_MODEL, settings.OLLAMA_FALLBACK_MODEL)
        if not _ollama_has_model(m, available)
    ]
    if missing:
        hint = "; ".join(f"ollama pull {m}" for m in missing)
        return False, f"Ollama reachable but missing models: {', '.join(missing)}. Run: {hint}"

    return True, (
        f"Ollama at {url}; models {settings.OLLAMA_MODEL} and "
        f"{settings.OLLAMA_FALLBACK_MODEL} available"
    )


def main() -> int:
    checks = [
        ("Python", check_python),
        ("ffmpeg", check_ffmpeg),
        ("Ollama", check_ollama),
    ]
    print("MTC environment check\n")
    all_ok = True
    for label, fn in checks:
        ok, detail = fn()
        status = "OK" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"[{status}] {label}: {detail}")
    print()
    if all_ok:
        print("All checks passed.")
    else:
        print("Some checks failed. Fix items marked FAIL above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
