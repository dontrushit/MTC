"""Merge per-channel transcripts into a single time-ordered dialog."""

from __future__ import annotations

from app.asr.transcribe import Segment

MERGE_GAP_SEC = 1.0


def merge_dialog(
    segments_manager: list[Segment],
    segments_client: list[Segment],
) -> list[Segment]:
    """Sort by start time; merge consecutive same-speaker turns if pause < 1 s."""
    combined = sorted(
        [*segments_manager, *segments_client],
        key=lambda s: (s.start, s.end),
    )
    if not combined:
        return []

    merged: list[Segment] = [combined[0]]
    for seg in combined[1:]:
        prev = merged[-1]
        if seg.speaker == prev.speaker and (seg.start - prev.end) < MERGE_GAP_SEC:
            merged[-1] = Segment(
                speaker=prev.speaker,
                start=prev.start,
                end=max(prev.end, seg.end),
                text=f"{prev.text} {seg.text}".strip(),
            )
        else:
            merged.append(seg)
    return merged
