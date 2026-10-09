"""Whisper backend selection: mlx on macOS, faster-whisper on Linux."""

from __future__ import annotations

import pytest

from app.asr.backend import resolve_whisper_backend, resolve_whisper_model
from app.config import settings


def test_auto_backend_is_mlx_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WHISPER_BACKEND", "auto")
    assert resolve_whisper_backend("Darwin") == "mlx"


def test_auto_backend_is_faster_whisper_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WHISPER_BACKEND", "auto")
    assert resolve_whisper_backend("Linux") == "faster-whisper"


def test_explicit_backend_overrides_os(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WHISPER_BACKEND", "mlx")
    assert resolve_whisper_backend("Linux") == "mlx"
    monkeypatch.setattr(settings, "WHISPER_BACKEND", "faster-whisper")
    assert resolve_whisper_backend("Darwin") == "faster-whisper"


def test_invalid_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WHISPER_BACKEND", "openai")
    with pytest.raises(ValueError, match="WHISPER_BACKEND"):
        resolve_whisper_backend("Linux")


def test_linux_maps_default_mlx_repo_to_ct2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
    assert resolve_whisper_model("faster-whisper") == "large-v3-turbo"
    assert resolve_whisper_model("mlx") == "mlx-community/whisper-large-v3-turbo"


def test_linux_keeps_ct2_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WHISPER_MODEL", "large-v3-turbo")
    assert resolve_whisper_model("faster-whisper") == "large-v3-turbo"


def test_linux_keeps_local_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WHISPER_MODEL", "models/whisper-large-v3-turbo")
    assert resolve_whisper_model("faster-whisper") == "models/whisper-large-v3-turbo"
