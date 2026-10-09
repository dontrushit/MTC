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

    def fake_transcribe(audio: np.ndarray, **kwargs: object) -> dict:
        nonlocal call_count
        call_count += 1
        text = "first" if call_count == 1 else "second"
        return {
            "segments": [
                {
                    "text": text,
                    "start": 0.0,
                    "end": 1.0,
                    "no_speech_prob": 0.1,
                    "compression_ratio": 1.0,
                }
            ]
        }

    monkeypatch.setattr("app.asr.transcribe.mlx_whisper.transcribe", fake_transcribe)

    segments = transcribe_channel(wav_path, SpeakerRole.MANAGER)
    assert len(segments) == 2
    assert segments[0].start == 0.0
    assert segments[0].end == 1.0
    assert segments[0].text == "first"
    assert segments[1].start == 3.0
    assert segments[1].end == 4.0
    assert segments[1].text == "second"
