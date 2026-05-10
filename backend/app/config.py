"""Application settings loaded from environment / .env file.

Всі значення мають типи. Невказані змінні беруться зі значень за замовчуванням,
що дозволяє запустити dev-режим без повного .env.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global application configuration.

    Керується через змінні середовища або backend/.env файл.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_name: str = "git-trainer-backend"
    debug: bool = True
    log_level: str = "INFO"

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://user:pass@localhost:5432/gittrainer",
        description="Async SQLAlchemy DSN (asyncpg driver).",
    )

    # --- Auth ---
    secret_key: str = Field(
        default="dev-secret-change-me",
        description="HMAC secret for session tokens. MUST be set in production.",
    )
    access_token_ttl_minutes: int = 60

    # --- Docker sandbox ---
    docker_socket: str = "/var/run/docker.sock"
    sandbox_image: str = "git-trainer-sandbox:latest"
    max_rooms: int = 50

    # --- CORS ---
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        description="Whitelist фронтенд-origin-ів для dev/prod.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Кеш налаштувань — один екземпляр на процес."""
    return Settings()
