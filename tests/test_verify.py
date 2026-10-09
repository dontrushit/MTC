"""Tests for quote verification against utterances."""

from __future__ import annotations

from app.db.models import SpeakerRole, Utterance
from app.extraction.schema import ExtractedAgreement
from app.extraction.verify import verify_agreements


def _utt(idx: int, speaker: SpeakerRole, text: str) -> Utterance:
    return Utterance(
        call_id=1,
        speaker=speaker,
        start_sec=float(idx),
        end_sec=float(idx) + 1,
        text=text,
    )


def test_exact_quote_kept() -> None:
    utterances = [_utt(0, SpeakerRole.MANAGER, "Я вышлю КП до пятницы.")]
    ag = ExtractedAgreement(
        action="выслать КП",
        responsible="manager",
        due_text="до пятницы",
        quote="Я вышлю КП до пятницы",
        utterance_index=0,
    )
    out = verify_agreements(utterances, [ag])
    assert len(out) == 1
    assert out[0].quote == ag.quote


def test_quote_with_different_punctuation() -> None:
    utterances = [_utt(0, SpeakerRole.CLIENT, "Оплатим, 150 тысяч рублей, до 20 числа.")]
    ag = ExtractedAgreement(
        action="оплатить",
        responsible="client",
        due_text="до 20 числа",
        amount="150000 RUB",
        quote="Оплатим 150 тысяч рублей до 20 числа",
        utterance_index=0,
    )
    out = verify_agreements(utterances, [ag])
    assert len(out) == 1


def test_quote_found_in_neighbor_repair_index() -> None:
    utterances = [
        _utt(0, SpeakerRole.MANAGER, "Добрый день."),
        _utt(1, SpeakerRole.MANAGER, "Завтра перезвоню в 11."),
    ]
    ag = ExtractedAgreement(
        action="перезвонить",
        responsible="manager",
        due_text="завтра",
        quote="Завтра перезвоню",
        utterance_index=0,
    )
    out = verify_agreements(utterances, [ag])
    assert len(out) == 1
    assert out[0].utterance_index == 1


def test_fabricated_quote_dropped() -> None:
    utterances = [_utt(0, SpeakerRole.CLIENT, "Спасибо, до свидания.")]
    ag = ExtractedAgreement(
        action="оплатить",
        responsible="client",
        quote="Мы оплатим миллион завтра",
        utterance_index=0,
    )
    out = verify_agreements(utterances, [ag])
    assert out == []
