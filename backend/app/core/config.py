from typing import List, Optional
from pathlib import Path

from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Look for .env in backend/ first, then fall back to project root (../)
# This handles both: running from backend/ and running from project root
_HERE = Path(__file__).resolve().parent.parent.parent  # backend/
_ROOT = _HERE.parent                                    # Pyra-main/

_ENV_FILES = []
if (_HERE / ".env").exists():
    _ENV_FILES.append(str(_HERE / ".env"))
if (_ROOT / ".env").exists():
    _ENV_FILES.append(str(_ROOT / ".env"))

# Always include both paths so pydantic-settings searches both
_ENV_FILES = [str(_HERE / ".env"), str(_ROOT / ".env")]


class Settings(BaseSettings):
    app_name: str = "PyraAI"
    app_version: str = "0.1.0"
    env: str = "development"
    debug: bool = True

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

    # CORS
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if value is None:
            return [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ]
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
        env_file=_ENV_FILES,      # checks backend/.env then Pyra-main/.env
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()