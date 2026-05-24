"""Application settings, loaded from environment via pydantic-settings."""

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the backend.

    Values are read from environment variables (case-insensitive) and a
    local `.env` file if present. See README for the full table.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # SQLAlchemy URL — psycopg v3 driver.
    database_url: str = (
        "postgresql+psycopg://claudeaws:claudeaws@localhost:5432/claudeaws"
    )

    # AWS integration mode: "mock" (default, in-memory/offline) or "real".
    aws_mode: str = "mock"

    # JWT signing config for PoC auth.
    jwt_secret: str = "dev-secret-change-me-to-a-random-32B+-value"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 480

    # Allowed CORS origins for the frontend. Accepts a comma-separated string
    # via the CORS_ORIGINS env var, or a list. NoDecode disables pydantic-
    # settings' default JSON decoding of list fields so the validator below
    # can split a plain comma-separated string (e.g. "http://localhost:5173").
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # Background usage polling interval in seconds (default 2 minutes).
    poll_interval_seconds: int = 120

    # Base tokens-per-minute rate for the mock usage simulator.
    usage_tokens_per_minute: int = 8000

    # Set to False to disable the background poller (useful in test environments).
    poller_enabled: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
