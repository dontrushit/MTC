"""Speaker labeling and mono-vs-stereo detection. The voice encoder is not loaded."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from app.audio.diarize import label_segments, merge_labeled
from app.audio.layout import is_separated_stereo


def _vec(axis: int) -> np.ndarray:
    vector = np.zeros(4, dtype=np.float32)
    vector[axis] = 1.0
    return vector


def test_two_voices_keep_order() -> None:
    segments = [(0.0, 2.0), (2.5, 4.0), (4.5, 6.0)]
    voice_a, voice_b = _vec(1), _vec(2)
    labels = label_segments(segments, [voice_a, voice_b, voice_a])
    assert labels[0] == 0
    assert labels[1] == 1
    assert labels[2] == 0


def test_second_voice_starting_is_relabeled_to_manager() -> None:
    segments = [(0.0, 2.0), (3.0, 5.0)]
    labels = label_segments(segments, [_vec(2), _vec(1)])
    assert labels == [0, 1]


def test_identical_embeddings_are_one_speaker() -> None:
    voice = _vec(3)
    segments = [(0.0, 2.0), (3.0, 5.0)]
    assert label_segments(segments, [voice, voice.copy()]) == [0, 0]


def test_short_segment_follows_neighbor() -> None:
    segments = [(0.0, 2.0), (2.2, 2.5), (3.0, 5.0)]
    labels = label_segments(segments, [_vec(1), None, _vec(2)])
    assert labels == [0, 1, 1]


def test_merge_same_speaker_across_short_gap() -> None:
    segments = [(0.0, 1.0), (1.2, 2.0), (3.0, 4.0)]
    merged = merge_labeled(segments, [0, 0, 1])
    assert merged == [(0.0, 2.0, 0), (3.0, 4.0, 1)]


def _ffmpeg(path: Path, *args: str) -> None:
    subprocess.run(["ffmpeg", "-y", *args, str(path)], capture_output=True, check=True)


def test_real_stereo_is_separated(tmp_path: Path) -> None:
    path = tmp_path / "stereo.wav"
    _ffmpeg(
        path,
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:duration=1",
        "-filter_complex",
        "[0:a][1:a]amerge=inputs=2",
        "-ar",
        "16000",
    )
    assert is_separated_stereo(path)


def test_identical_channels_are_mixed(tmp_path: Path) -> None:
    path = tmp_path / "dual.wav"
    _ffmpeg(
        path,
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1",
        "-ac",
        "2",
        "-ar",
        "16000",
    )
    assert not is_separated_stereo(path)


def test_mono_is_mixed(tmp_path: Path) -> None:
    path = tmp_path / "mono.wav"
    _ffmpeg(path, "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-ac", "1")
    assert not is_separated_stereo(path)
