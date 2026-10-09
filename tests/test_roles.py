"""Speaker role correction from an employee phrase or a model decision."""

from app.asr.roles import resolve_roles
from app.asr.transcribe import Segment
from app.db.models import SpeakerRole


def _seg(speaker: SpeakerRole, text: str, start: float = 0.0) -> Segment:
    return Segment(speaker=speaker, start=start, end=start + 1.0, text=text)


def test_employee_phrase_on_the_client_channel_swaps(monkeypatch) -> None:
    def unused(_segments: list[Segment]) -> SpeakerRole | None:
        raise AssertionError("phrase is enough, the model must not be called")

    monkeypatch.setattr("app.asr.roles._employee_by_model", unused)
    dialog = [
        _seg(SpeakerRole.MANAGER, "Алло, хочу заказать симку"),
        _seg(SpeakerRole.CLIENT, "Здравствуйте, работник МТС, слушаю вас", start=2.0),
    ]
    resolved = resolve_roles(dialog)
    assert resolved[0].speaker == SpeakerRole.CLIENT
    assert resolved[1].speaker == SpeakerRole.MANAGER
    assert resolved[1].text.startswith("Здравствуйте")


def test_employee_phrase_on_the_manager_channel_stays(monkeypatch) -> None:
    def unused(_segments: list[Segment]) -> SpeakerRole | None:
        raise AssertionError("phrase is enough, the model must not be called")

    monkeypatch.setattr("app.asr.roles._employee_by_model", unused)
    dialog = [
        _seg(SpeakerRole.MANAGER, "Я из МТС, меня зовут Анна"),
        _seg(SpeakerRole.CLIENT, "Хочу симку", start=2.0),
    ]
    resolved = resolve_roles(dialog)
    assert [seg.speaker for seg in resolved] == [SpeakerRole.MANAGER, SpeakerRole.CLIENT]


def test_model_can_swap_when_nobody_names_the_company(monkeypatch) -> None:
    monkeypatch.setattr("app.asr.roles._employee_by_model", lambda _segments: SpeakerRole.CLIENT)
    dialog = [
        _seg(SpeakerRole.MANAGER, "Алло, это по поводу тарифа"),
        _seg(SpeakerRole.CLIENT, "Добрый день, чем могу помочь?", start=2.0),
    ]
    resolved = resolve_roles(dialog)
    assert resolved[0].speaker == SpeakerRole.CLIENT
    assert resolved[1].speaker == SpeakerRole.MANAGER


def test_unclear_model_keeps_the_original_labels(monkeypatch) -> None:
    monkeypatch.setattr("app.asr.roles._employee_by_model", lambda _segments: None)
    dialog = [
        _seg(SpeakerRole.MANAGER, "Алло"),
        _seg(SpeakerRole.CLIENT, "Да", start=2.0),
    ]
    resolved = resolve_roles(dialog)
    assert [seg.speaker for seg in resolved] == [SpeakerRole.MANAGER, SpeakerRole.CLIENT]


def test_one_voice_is_left_as_is(monkeypatch) -> None:
    def unused(_segments: list[Segment]) -> SpeakerRole | None:
        raise AssertionError("one voice has nothing to swap")

    monkeypatch.setattr("app.asr.roles._employee_by_model", unused)
    dialog = [_seg(SpeakerRole.MANAGER, "Алло, никого нет")]
    assert resolve_roles(dialog) == dialog
