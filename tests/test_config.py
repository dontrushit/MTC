"""Configuration import smoke tests."""

from app.config import Settings, settings


def test_settings_singleton_import() -> None:
    assert isinstance(settings, Settings)
    assert settings.DB_URL.startswith("sqlite:")
    assert settings.OLLAMA_MODEL
    assert settings.TZ == "Europe/Moscow"


def test_settings_defaults_without_env_file() -> None:
    defaults = Settings(_env_file=None)
    assert defaults.OLLAMA_MODEL == "qwen2.5:14b"
