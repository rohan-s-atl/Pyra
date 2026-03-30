"""
config.py — Application settings.

PATCHES
-------
1. debug now defaults to False. Was True — exposed tracebacks in production
   error responses when ENV was not explicitly set.
2. Added startup warning when ENV is not explicitly configured so deployments
   don't silently run in development mode.
"""
import logging
import os
from typing import List, Optional
from pathlib import Path

from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_HERE = Path(__file__).resolve().parent.parent.parent  # backend/
_ROOT = _HERE.parent                                    # PyraAI-main/

_ENV_FILES = [str(_HERE / ".env"), str(_ROOT / ".env")]

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    app_name: str = "PyraAI"
    app_version: str = "0.1.0"
    env: str = "development"
    debug: bool = False   # FIX: was True — never expose tracebacks by default

    # Database
    database_url: str = Field(
        default="postgresql://postgres@localhost:5432/pyra",
        alias="DATABASE_URL"
    )

    # Security
    secret_key: Optional[str] = None
    access_token_expire_hours: int = 8

    # External APIs
    anthropic_api_key: Optional[str] = None
    nasa_firms_api_key: Optional[str] = None
    airnow_api_key: Optional[str] = None

    # Routing
    local_osrm_url: str = "http://localhost:5001/route/v1/driving"
    openrouteservice_api_key: Optional[str] = None
    mapbox_token: Optional[str] = None

    # CORS
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if value is None:
            return ["http://localhost:5173", "http://127.0.0.1:5173"]
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}

    @property
    def is_development(self) -> bool:
        return self.env.lower() in {"dev", "development", "local"}

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()

# Warn loudly if ENV was not explicitly set in a non-local context
if not os.environ.get("ENV") and not (settings._env_file if hasattr(settings, '_env_file') else None):
    if settings.is_development:
        logger.warning(
            "ENV environment variable not set — running in development mode. "
            "Set ENV=production on Railway to enable production hardening."
        )