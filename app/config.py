"""Application settings loaded from environment and `.env`."""

import platform
import sys
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_asr_backend() -> Literal["mlx", "faster"]:
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "mlx"
    return "faster"


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
    ASR_BACKEND: Literal["mlx", "faster"] = _default_asr_backend()
    # Empty means backend default: mlx -> large-v3-turbo, faster (CPU) -> small
    WHISPER_MODEL: str = ""
    ASR_CPU_THREADS: int = 0
    TELEGRAM_TOKEN: str = ""
    HF_TOKEN: str = ""
    TZ: str = "Europe/Moscow"
    API_URL: str = "http://localhost:8000"

    @model_validator(mode="after")
    def _fill_whisper_model(self) -> "Settings":
        if not self.WHISPER_MODEL:
            self.WHISPER_MODEL = (
                "mlx-community/whisper-large-v3-turbo" if self.ASR_BACKEND == "mlx" else "small"
            )
        return self


settings = Settings()
