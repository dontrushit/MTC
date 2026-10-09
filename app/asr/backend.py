"""Whisper backends: mlx-whisper on macOS, faster-whisper on Linux."""

from __future__ import annotations

import platform
from typing import Any

from app.config import settings

_FASTER_WHISPER_MODEL: Any = None
_FASTER_WHISPER_KEY: tuple[str, str, str] | None = None

_MLX_TO_CT2 = {
    "mlx-community/whisper-large-v3-turbo": "large-v3-turbo",
    "mlx-community/whisper-large-v3": "large-v3",
    "mlx-community/whisper-medium": "medium",
    "mlx-community/whisper-small": "small",
    "mlx-community/whisper-base": "base",
    "mlx-community/whisper-tiny": "tiny",
}

VALID_BACKENDS = frozenset({"auto", "mlx", "faster-whisper"})


def resolve_whisper_backend(system: str | None = None) -> str:
    """Return `mlx` or `faster-whisper`. `auto` follows the OS: mlx on Darwin."""
    configured = settings.WHISPER_BACKEND.strip().lower()
    if configured not in VALID_BACKENDS:
        allowed = ", ".join(sorted(VALID_BACKENDS))
        msg = f"WHISPER_BACKEND must be one of: {allowed} (got {settings.WHISPER_BACKEND!r})"
        raise ValueError(msg)
    if configured != "auto":
        return configured
    sysname = system if system is not None else platform.system()
    if sysname == "Darwin":
        return "mlx"
    return "faster-whisper"


def resolve_whisper_model(backend: str | None = None) -> str:
    """Model id or path for the active backend.

    macOS keeps mlx repo ids / mlx weight directories as-is. On Linux, known
    mlx-community ids are mapped to CTranslate2 names used by faster-whisper.
    """
    backend = backend or resolve_whisper_backend()
    raw = settings.WHISPER_MODEL.strip()
    if backend == "mlx":
        return raw
    mapped = _MLX_TO_CT2.get(raw)
    if mapped:
        return mapped
    prefix = "mlx-community/whisper-"
    if raw.startswith(prefix) and raw[len(prefix) :]:
        return raw[len(prefix) :]
    return raw


def resolve_whisper_device() -> str:
    configured = settings.WHISPER_DEVICE.strip().lower()
    if configured != "auto":
        return configured
    if resolve_whisper_backend() == "mlx":
        return "mlx"
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def resolve_whisper_compute_type(device: str | None = None) -> str:
    configured = settings.WHISPER_COMPUTE_TYPE.strip().lower()
    if configured != "auto":
        return configured
    device = device or resolve_whisper_device()
    if device == "cuda":
        return "float16"
    return "int8"


def transcribe_audio(audio: Any) -> dict:
    """Run ASR on a 16 kHz float32 mono chunk; return an mlx-like result dict."""
    backend = resolve_whisper_backend()
    if backend == "mlx":
        return _transcribe_mlx(audio)
    if backend == "faster-whisper":
        return _transcribe_faster_whisper(audio)
    msg = f"Unsupported Whisper backend: {backend}"
    raise ValueError(msg)


def _transcribe_mlx(audio: Any) -> dict:
    try:
        import mlx_whisper
    except ImportError as exc:
        raise RuntimeError(
            "mlx-whisper is required for the mlx backend (macOS). "
            "Install with: uv pip install -e '.[asr]'"
        ) from exc
    return mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=resolve_whisper_model("mlx"),
        language="ru",
        condition_on_previous_text=False,
    )


def _faster_whisper_model():
    global _FASTER_WHISPER_MODEL, _FASTER_WHISPER_KEY
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is required on Linux. Install with: uv pip install -e '.[asr]'"
        ) from exc

    model_name = resolve_whisper_model("faster-whisper")
    device = resolve_whisper_device()
    if device == "mlx":
        device = "cpu"
    compute_type = resolve_whisper_compute_type(device)
    key = (model_name, device, compute_type)
    if _FASTER_WHISPER_MODEL is None or _FASTER_WHISPER_KEY != key:
        try:
            _FASTER_WHISPER_MODEL = WhisperModel(
                model_name, device=device, compute_type=compute_type
            )
        except Exception as exc:
            raise RuntimeError(
                "Failed to load faster-whisper model "
                f"{model_name!r} (device={device}, compute_type={compute_type}). "
                "On Linux use a CTranslate2 model such as large-v3-turbo, not mlx weights. "
                f"Original error: {exc}"
            ) from exc
        _FASTER_WHISPER_KEY = key
    return _FASTER_WHISPER_MODEL


def _transcribe_faster_whisper(audio: Any) -> dict:
    import numpy as np

    model = _faster_whisper_model()
    segments, _info = model.transcribe(
        np.ascontiguousarray(audio, dtype=np.float32),
        language="ru",
        condition_on_previous_text=False,
        vad_filter=False,
    )
    raw_segments = []
    for seg in segments:
        raw_segments.append(
            {
                "text": seg.text,
                "start": float(seg.start),
                "end": float(seg.end),
                "no_speech_prob": float(getattr(seg, "no_speech_prob", 0.0)),
                "compression_ratio": float(getattr(seg, "compression_ratio", 0.0)),
            }
        )
    return {"segments": raw_segments}
