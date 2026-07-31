from pathlib import Path
from typing import List, Union

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, field_validator

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# ======================================================
# Settings configuration
# ======================================================


class Settings(BaseSettings):
    # App settings
    SERVICE_NAME: str = "PREPARE Extraction Tool"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "local"

    # Security settings
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    # Database settings
    DATABASE_URL: str
    ELASTICSEARCH_URL: str

    # Upload settings
    MAX_UPLOAD_SIZE_MB: int = 2048  # 2 GB default

    # Service settings
    # Bioner service URL. Defaults to localhost for local runs; overridden to the
    # compose service name (http://bioner:5600) in docker-compose.
    EXTRACT_HOST: str = "http://localhost:5600"

    # Model settings
    EMBEDDING_MODEL_SENTENCE: Union[str, None] = None
    EMBEDDING_MODEL_MODEL2VEC: Union[str, None] = None

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Validate that DATABASE_URL is a valid PostgreSQL connection string."""
        if not v.startswith(("postgresql://", "postgresql+psycopg2://")):
            raise ValueError(
                "DATABASE_URL must be a valid PostgreSQL URL starting with "
                "'postgresql://' or 'postgresql+psycopg2://'"
            )
        return v

    @field_validator("ELASTICSEARCH_URL")
    @classmethod
    def validate_elasticsearch_url(cls, v: str) -> str:
        """Validate that ELASTICSEARCH_URL is a valid HTTP(S) URL."""
        if not v.startswith(("http://", "https://")):
            raise ValueError(
                "ELASTICSEARCH_URL must be a valid HTTP(S) URL starting with "
                "'http://' or 'https://'"
            )
        return v

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        if isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # ======================================================
    # Environment setting
    # ======================================================

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
