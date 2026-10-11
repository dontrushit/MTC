"""Application settings loaded from environment and `.env`."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Договорённости по звонкам"
    DATA_DIR: Path = Path("data")
    # Текст уведомления абонентов о записи (озвучивается АТС перед разговором).
    IVR_NOTICE_TEXT: str = (
        "Внимание! Разговор записывается и автоматически обрабатывается "
        "для фиксации договорённостей."
    )
    # Путь к модели piper (fallback синтеза уведомления без espeak-ng).
    IVR_PIPER_MODEL: str = ""
    # Telegram-уведомления «отчёт готов». Без токена функция выключена.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_USERNAME: str = ""
    PUBLIC_BASE_URL: str = ""
    DB_URL: str = "sqlite:///data/mtc.db"
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:14b"
    OLLAMA_FALLBACK_MODEL: str = "qwen2.5:7b"
    OLLAMA_NUM_CTX: int = 16384
    WHISPER_MODEL: str = "mlx-community/whisper-large-v3-turbo"
    WHISPER_BACKEND: str = "auto"
    WHISPER_DEVICE: str = "auto"
    WHISPER_COMPUTE_TYPE: str = "auto"
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
