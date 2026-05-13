"""Centralized application configuration.

Single source of truth for runtime settings. All settings are typed,
loaded from environment variables (with optional `.env` fallback), and
accessed through a cached `get_settings()` dependency so the rest of the
codebase never reads `os.environ` directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "development", "staging", "production", "test"]


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Add new settings here as the platform grows (DB URLs, AI provider
    keys, feature flags, etc.). Everything must be typed and documented.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "Operious AI"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = "local"

    API_V1_PREFIX: str = "/api/v1"

    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool | None = None

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_local(self) -> bool:
        return self.ENVIRONMENT in ("local", "development", "test")

    @property
    def use_json_logs(self) -> bool:
        # Explicit override wins; otherwise JSON for any non-local environment.
        if self.LOG_JSON is not None:
            return self.LOG_JSON
        return not self.is_local


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached `Settings` instance.

    Cached so repeated `Depends(get_settings)` calls are free and so the
    application observes a single, consistent configuration snapshot.
    """

    return Settings()
