"""
Application settings loaded from environment variables.

Uses pydantic-settings for type-safe, validated configuration.
All secrets and deployment-specific values come from .env — nothing is hardcoded.
"""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Telegram ---
    telegram_bot_token: str

    # --- Gemini ---
    gemini_api_key: str
    gemini_model: str = "gemini-2.0-flash"

    # --- Google Sheets ---
    google_service_account_file: str
    google_spreadsheet_id: str = ""

    # --- Logging ---
    log_level: str = "INFO"

    @property
    def service_account_path(self) -> Path:
        """Resolve the service account file path relative to project root."""
        raw = Path(self.google_service_account_file)
        if raw.is_absolute():
            return raw
        return Path(__file__).resolve().parent.parent / raw


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of application settings."""
    return Settings()
