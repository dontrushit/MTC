"""Configuration import smoke tests."""

from app.config import Settings, settings


def test_settings_singleton_import() -> None:
    assert isinstance(settings, Settings)
    assert settings.DB_URL.startswith("sqlite:")
    assert settings.OLLAMA_MODEL == "qwen2.5:14b"
    assert settings.TZ == "Europe/Moscow"
