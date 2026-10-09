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

from app.asr.backend import (  # noqa: E402
    resolve_whisper_backend,
    resolve_whisper_compute_type,
    resolve_whisper_device,
    resolve_whisper_model,
)
from app.config import settings  # noqa: E402
from app.system import ffmpeg_install_hint, python_version_ok  # noqa: E402


def check_python() -> tuple[bool, str]:
    ver = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
    if python_version_ok(version_info.major, version_info.minor):
        return True, f"Python {ver}"
    return (
        False,
        f"Python {ver} (need 3.11 or 3.12, not 3.13+). Recreate .venv with 3.11/3.12.",
    )


def check_ffmpeg() -> tuple[bool, str]:
    path = shutil.which("ffmpeg")
    if path:
        return True, f"ffmpeg found at {path}"
    return False, f"ffmpeg not in PATH. Install: {ffmpeg_install_hint()}"


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


def check_asr() -> tuple[bool, str]:
    try:
        backend = resolve_whisper_backend()
        model = resolve_whisper_model(backend)
        device = resolve_whisper_device()
        compute = resolve_whisper_compute_type(device)
    except ValueError as exc:
        return False, str(exc)

    if backend == "mlx":
        try:
            import mlx_whisper  # noqa: F401
        except ImportError:
            return False, "mlx-whisper not installed. On macOS: uv pip install -e '.[asr]'"
        return True, f"mlx-whisper; model {model}"

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False, "faster-whisper not installed. On Linux: uv pip install -e '.[asr]'"
    return True, f"faster-whisper; model {model}; device {device}; compute {compute}"


def main() -> int:
    checks = [
        ("Python", check_python),
        ("ffmpeg", check_ffmpeg),
        ("ASR", check_asr),
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
