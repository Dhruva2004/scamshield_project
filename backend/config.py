"""
ScamShield AI - backend/config.py
=================================
Single source of truth for *all* configuration.

Why this file exists
--------------------
A professional application never hardcodes settings (URLs, API keys, DB paths)
inside the code. Instead we read them from environment variables, usually
loads from a `.env` file during local development.

We use `pydantic-settings`:
  * `BaseSettings` automatically reads environment variables.
  * Every field is type-validated, so `DEBUG=notabool` fails loudly at start-up
    instead of silently becoming the string "notabool".
  * `Settings()` is cached with `lru_cache`, so the whole app shares ONE object.

The rest of the code should only ever do:
    from backend.config import get_settings
    settings = get_settings()
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = the folder that contains backend/, frontend/, ml/, models/ ...
# Path(__file__) -> .../ScamShield-AI/backend/config.py
#   .resolve().parent  -> .../ScamShield-AI/backend
#   .parent            -> .../ScamShield-AI
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed, validated application settings."""

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_name: str = "ScamShield AI"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    # Hosting platforms (Render, Railway, Fly, Heroku) inject the port to bind on
    # as $PORT, while .env uses API_PORT. AliasChoices accepts either name, with
    # PORT taking precedence because it is the platform's runtime contract.
    api_port: int = Field(default=8000, validation_alias=AliasChoices("PORT", "api_port"))
    api_prefix: str = "/api/v1"

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    # Stored as a comma separated STRING on purpose: pydantic-settings would
    # otherwise try to JSON-decode a List field out of .env and fail on
    # "http://a:1,http://b:2". Use the `cors_origin_list` property instead.
    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"
    # Optional shared secret. If set, protected endpoints require header X-API-Key.
    api_key: str = ""

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    # SQLite by default. For PostgreSQL just change the URL:
    #   postgresql+psycopg://user:pass@host:5432/scamshield
    # `DATA_DIR` lets a hosting platform point the database at a mounted disk
    # (e.g. Render disk at /var/data) without editing the URL by hand.
    database_url: str = os.getenv("DATABASE_URL", "") or (
        f"sqlite:///{os.getenv('DATA_DIR', './data').rstrip('/')}/scamshield.db"
    )
    db_echo: bool = False

    # ------------------------------------------------------------------
    # Machine learning artefacts
    # ------------------------------------------------------------------
    model_dir: Path = PROJECT_ROOT / "models"
    vectorizer_dir: Path = PROJECT_ROOT / "ml" / "vectorizers"
    active_model: str = "model_logistic_regression.joblib"
    ml_spam_threshold: float = 0.50

    # ------------------------------------------------------------------
    # Gemini / Generative AI
    # ------------------------------------------------------------------
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_timeout_seconds: int = 25
    gemini_enabled: bool = True

    # ------------------------------------------------------------------
    # Privacy
    # ------------------------------------------------------------------
    store_raw_message: bool = True
    privacy_salt: str = "change-this-to-a-long-random-string"
    history_max_rows: int = 5000

    # ------------------------------------------------------------------
    # Frontend
    # ------------------------------------------------------------------
    api_base_url: str = "http://localhost:8000"

    # ------------------------------------------------------------------
    # pydantic-settings configuration
    # ------------------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",       # unknown variables in .env are ignored, not fatal
        case_sensitive=False,  # GEMINI_API_KEY and gemini_api_key both work
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("model_dir", "vectorizer_dir", mode="after")
    @classmethod
    def _resolve_project_paths(cls, value: Path) -> Path:
        """Turn './models' into an absolute path anchored at the project root."""
        path = Path(value)
        if not path.is_absolute():
            path = (PROJECT_ROOT / str(path).lstrip("./")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @field_validator("database_url", mode="before")
    @classmethod
    def _default_database_url(cls, value):
        """
        Treat a blank DATABASE_URL as "not set".

        pydantic-settings copies an environment variable over the field default
        even when the variable is an empty string, so `DATABASE_URL=` in a .env
        file (a very easy mistake) used to produce an empty URL and a runtime
        error on the first query. Instead we fall back to DATA_DIR/data.
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            data_dir = os.getenv("DATA_DIR", "./data").rstrip("/")
            return f"sqlite:///{data_dir}/scamshield.db"
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def _resolve_sqlite_path(cls, value: str) -> str:
        """
        Make SQLite paths absolute so the database file always lands in the
        same place, no matter which directory you started the server from.

        'sqlite:///./data/scamshield.db'
              -> 'sqlite:////abs/path/ScamShield-AI/data/scamshield.db'
        """
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            return value  # PostgreSQL / other engines: leave untouched

        raw_path = value[len(prefix):]
        # Already absolute (starts with '/') -> nothing to do.
        if raw_path.startswith("/"):
            return value

        absolute = (PROJECT_ROOT / raw_path.lstrip("./")).resolve()
        absolute.parent.mkdir(parents=True, exist_ok=True)
        return f"{prefix}{absolute}"

    # ------------------------------------------------------------------
    # Derived helpers (not settings, just convenience)
    # ------------------------------------------------------------------
    @property
    def cors_origin_list(self) -> List[str]:
        """
        CORS origins as a real list.

        Accepts either a comma separated string ("http://a:1,http://b:2") or a
        value that already looks like a list. "*" is passed through as-is.
        """
        raw = self.cors_origins or ""
        if isinstance(raw, (list, tuple)):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def gemini_available(self) -> bool:
        """True only when Gemini is enabled AND a key is present."""
        return bool(self.gemini_enabled and self.gemini_api_key.strip())

    @property
    def active_model_path(self) -> Path:
        return self.model_dir / self.active_model

    @property
    def sqlite_path(self) -> str:
        """Plain filesystem path of the SQLite database ('' for non-SQLite)."""
        prefix = "sqlite:///"
        return self.database_url[len(prefix):] if self.database_url.startswith(prefix) else ""

    def describe(self) -> dict:
        """
        Safe summary used by /api/v1/health and the dashboard footer.
        NOTE: secrets are deliberately *redacted* here.
        """
        return {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "environment": self.environment,
            "debug": self.debug,
            "database_backend": self.database_url.split(":")[0],
            "model_available": self.active_model_path.exists(),
            "gemini_configured": self.gemini_available,
            "store_raw_message": self.store_raw_message,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the single, cached Settings instance.

    `lru_cache` guarantees the .env file is parsed once per process, which is
    both faster and avoids surprising re-reads during tests.
    """
    return Settings()


def reload_settings() -> Settings:
    """Clear the cache and re-read .env (used by tests)."""
    os.environ.pop("_", None)
    get_settings.cache_clear()
    return get_settings()


if __name__ == "__main__":  # quick manual smoke-test: python -m backend.config
    import json

    print(json.dumps(get_settings().describe(), indent=2))
    print("PROJECT_ROOT =", PROJECT_ROOT)
    print("DB file      =", get_settings().sqlite_path)
    print("Model path   =", get_settings().active_model_path)
