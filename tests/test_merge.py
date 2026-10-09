"""Tests for dialog merge."""

from app.asr.merge import merge_dialog
from app.asr.transcribe import Segment
from app.db.models import SpeakerRole


def _seg(speaker: SpeakerRole, start: float, end: float, text: str) -> Segment:
    return Segment(speaker=speaker, start=start, end=end, text=text)


def test_merge_sorts_by_start() -> None:
    manager = [_seg(SpeakerRole.MANAGER, 5.0, 6.0, "b")]
    client = [_seg(SpeakerRole.CLIENT, 0.0, 1.0, "a")]
    merged = merge_dialog(manager, client)
    assert [s.text for s in merged] == ["a", "b"]


def test_merge_same_speaker_within_gap() -> None:
    manager = [
        _seg(SpeakerRole.MANAGER, 0.0, 1.0, "первая"),
        _seg(SpeakerRole.MANAGER, 1.4, 2.4, "вторая"),
    ]
    merged = merge_dialog(manager, [])
    assert len(merged) == 1
    assert merged[0].start == 0.0
    assert merged[0].end == 2.4
    assert merged[0].text == "первая вторая"


def test_merge_does_not_merge_different_speakers() -> None:
    manager = [_seg(SpeakerRole.MANAGER, 0.0, 1.0, "m")]
    client = [_seg(SpeakerRole.CLIENT, 0.2, 1.2, "c")]
    merged = merge_dialog(manager, client)
    assert len(merged) == 2


def test_merge_gap_at_least_half_second_not_merged() -> None:
    manager = [
        _seg(SpeakerRole.MANAGER, 0.0, 1.0, "one"),
        _seg(SpeakerRole.MANAGER, 1.6, 2.6, "two"),
    ]
    merged = merge_dialog(manager, [])
    assert len(merged) == 2
