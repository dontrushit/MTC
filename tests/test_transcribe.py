"""Unit tests for per-VAD-chunk transcription (no Whisper model)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.asr.transcribe import transcribe_channel
from app.db.models import SpeakerRole


def test_two_vad_chunks_produce_two_timed_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav_path = tmp_path / "channel.wav"
    sf.write(wav_path, np.zeros(16000 * 10, dtype=np.float32), 16000)

    monkeypatch.setattr(
        "app.asr.transcribe.speech_segments",
        lambda _path: [(0.0, 1.0), (3.0, 4.0)],
    )

    call_count = 0

    def fake_transcribe(audio: np.ndarray) -> list[dict]:
        nonlocal call_count
        call_count += 1
        text = "first" if call_count == 1 else "second"
        return [{"text": text, "no_speech_prob": 0.1, "compression_ratio": 1.0}]

    monkeypatch.setattr("app.asr.transcribe.transcribe_chunk", fake_transcribe)

    segments = transcribe_channel(wav_path, SpeakerRole.MANAGER)
    assert len(segments) == 2
    assert segments[0].start == 0.0
    assert segments[0].end == 1.0
    assert segments[0].text == "first"
    assert segments[1].start == 3.0
    assert segments[1].end == 4.0
    assert segments[1].text == "second"


@pytest.mark.parametrize(
    ("backend", "expected"),
    [("mlx", "mlx-community/whisper-large-v3-turbo"), ("faster", "small")],
)
def test_whisper_model_default_depends_on_backend(backend: str, expected: str) -> None:
    from app.config import Settings

    s = Settings(_env_file=None, ASR_BACKEND=backend, WHISPER_MODEL="")
    assert s.WHISPER_MODEL == expected


def test_faster_backend_maps_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.asr import backends

    class FakeModel:
        def transcribe(self, audio: np.ndarray, **kwargs: object):
            seg = SimpleNamespace(text=" привет", no_speech_prob=0.2, compression_ratio=1.1)
            return iter([seg]), None

    monkeypatch.setattr(backends.settings, "ASR_BACKEND", "faster")
    monkeypatch.setattr(backends, "_faster_model", lambda: FakeModel())
    out = backends.transcribe_chunk(np.zeros(16000, dtype=np.float32))
    assert out == [{"text": " привет", "no_speech_prob": 0.2, "compression_ratio": 1.1}]
