from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = API_DIR.parents[1]


class Settings(BaseSettings):
    """Runtime configuration. Secrets live in gitignored .env files, never in code."""

    model_config = SettingsConfigDict(
        env_file=(API_DIR / ".env", REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "ShopFlow API"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://shopflow_app:change-me@localhost:5432/shopflow_dev"
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_echo: bool = False

    secret_key: str = "dev-only-insecure-secret-change-me"
    access_token_expire_minutes: int = 60 * 12
    password_hash_time_cost: int = 3

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    default_locale: str = "en"
    demo_data: bool = True

    # When enabled, unauthenticated read endpoints fall back to a demo manager
    # principal (Phase 1 behaviour). Write endpoints never use it. Flip off for
    # production so every request is authenticated.
    demo_mode: bool = True

    # Brute-force login protection: per identity+IP sliding window.
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300

    @field_validator("default_locale")
    @classmethod
    def validate_locale(cls, value: str) -> str:
        if value not in {"en", "bn"}:
            raise ValueError("default_locale must be 'en' or 'bn'")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
