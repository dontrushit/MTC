"""Application settings loaded from environment and `.env`."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATA_DIR: Path = Path("data")
    DB_URL: str = "sqlite:///data/mtc.db"
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:14b"
    OLLAMA_FALLBACK_MODEL: str = "qwen2.5:7b"
    WHISPER_MODEL: str = "mlx-community/whisper-large-v3-turbo"
    TELEGRAM_TOKEN: str = ""
    HF_TOKEN: str = ""
    TZ: str = "Europe/Moscow"
    API_URL: str = "http://localhost:8000"
    # MTS Автосекретарь. Empty user and password means the event URL is open.
    ATC_BASIC_USER: str = ""
    ATC_BASIC_PASSWORD: str = ""
    # GET template, for example https://host/recordings/{call_id}. Empty skips download.
    ATC_RECORDING_URL: str = ""
    # Used when the agent number matches nobody. Empty falls back to the first manager.
    ATC_MANAGER_ID: str = ""


settings = Settings()
