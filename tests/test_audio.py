"""Tests for ffmpeg probe, channel split, and VAD."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.audio.exceptions import MonoNotSupportedError
from app.audio.preprocess import split_channels
from app.audio.probe import probe
from app.audio.vad import speech_segments
from app.db.models import SpeakerRole


def _make_stereo_sine_left(path: Path, duration_sec: float = 2.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration_sec}",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=44100:cl=mono,atrim=0:{duration_sec}",
            "-filter_complex",
            "[0:a][1:a]amerge=inputs=2[aout]",
            "-map",
            "[aout]",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


def _make_mono(path: Path, duration_sec: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration_sec}",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


def test_probe_stereo(tmp_path: Path) -> None:
    stereo = tmp_path / "stereo.wav"
    _make_stereo_sine_left(stereo)
    info = probe(stereo)
    assert info.channels == 2
    assert info.sample_rate == 44100
    assert info.duration_sec == pytest.approx(2.0, abs=0.1)


def test_split_channels(tmp_path: Path) -> None:
    stereo = tmp_path / "stereo.wav"
    out_dir = tmp_path / "split"
    _make_stereo_sine_left(stereo)
    paths = split_channels(stereo, out_dir)
    assert paths[SpeakerRole.MANAGER].is_file()
    assert paths[SpeakerRole.CLIENT].is_file()
    mgr = probe(paths[SpeakerRole.MANAGER])
    cli = probe(paths[SpeakerRole.CLIENT])
    assert mgr.channels == 1
    assert cli.channels == 1
    assert mgr.sample_rate == 16000


def test_vad_empty_on_silent_channel(tmp_path: Path) -> None:
    stereo = tmp_path / "stereo.wav"
    out_dir = tmp_path / "split"
    _make_stereo_sine_left(stereo)
    paths = split_channels(stereo, out_dir)
    silent_segments = speech_segments(paths[SpeakerRole.CLIENT])
    assert silent_segments == []


def test_mono_raises(tmp_path: Path) -> None:
    mono = tmp_path / "mono.wav"
    _make_mono(mono)
    with pytest.raises(MonoNotSupportedError):
        split_channels(mono, tmp_path / "out")
