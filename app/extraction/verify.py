"""Quote verification against utterance text."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from app.db.models import SpeakerRole, Utterance
from app.extraction.schema import ExtractedAgreement

logger = logging.getLogger(__name__)

_FUZZY_RATIO = 0.85
_NEIGHBOR_RANGE = 2


def _normalize(text: str) -> str:
    t = text.lower().replace("ё", "е")
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _fuzzy_contains(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    h = _normalize(haystack)
    n = _normalize(needle)
    if not n:
        return False
    if n in h:
        return True
    n_len = len(n)
    if n_len > len(h):
        return SequenceMatcher(None, h, n).ratio() >= _FUZZY_RATIO
    best = 0.0
    for i in range(0, len(h) - n_len + 1):
        window = h[i : i + n_len]
        ratio = SequenceMatcher(None, window, n).ratio()
        if ratio > best:
            best = ratio
        if best >= _FUZZY_RATIO:
            return True
    return best >= _FUZZY_RATIO


def verify_agreements(
    utterances: list[Utterance],
    agreements: list[ExtractedAgreement],
) -> list[ExtractedAgreement]:
    """Drop agreements whose quote cannot be matched; fix utterance_index if nearby."""
    verified: list[ExtractedAgreement] = []
    for ag in agreements:
        idx = ag.utterance_index
        matched_idx: int | None = None

        if 0 <= idx < len(utterances) and _fuzzy_contains(utterances[idx].text, ag.quote):
            matched_idx = idx
        else:
            for delta in range(1, _NEIGHBOR_RANGE + 1):
                for sign in (-1, 1):
                    j = idx + sign * delta
                    if 0 <= j < len(utterances) and _fuzzy_contains(
                        utterances[j].text, ag.quote
                    ):
                        matched_idx = j
                        break
                if matched_idx is not None:
                    break

        if matched_idx is None:
            logger.warning(
                "Dropped agreement: quote not found (index=%s, quote=%r)",
                idx,
                ag.quote[:80],
            )
            continue

        speaker = utterances[matched_idx].speaker
        expected = SpeakerRole(ag.responsible)
        if speaker != expected:
            logger.warning(
                "Responsible %s does not match speaker %s at index %s; keeping agreement",
                ag.responsible,
                speaker.value,
                matched_idx,
            )

        if matched_idx != idx:
            ag = ag.model_copy(update={"utterance_index": matched_idx})
        verified.append(ag)

    return verified
