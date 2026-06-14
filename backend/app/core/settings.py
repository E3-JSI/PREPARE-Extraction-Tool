import secrets
import warnings
from pathlib import Path
from typing import List, Union

from typing_extensions import Self
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, field_validator, model_validator

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
    SECRET_KEY: str = secrets.token_urlsafe(32)
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
    EXTRACT_HOST: str = "http://0.0.0.0:5600"
    BIONER_URL = "http://localhost:5600"
    BACKEND_URL = "http://prepare-backend:8000"

    # Model settings
    EMBEDDING_MODEL_SENTENCE: Union[str, None] = None
    EMBEDDING_MODEL_MODEL2VEC: Union[str, None] = None

    BIONER_DEFAULT_MODEL: str = "urchade/gliner_small"
    BIONER_DEFAULT_MODEL_PVT: str = "ErikCalcina/synthetic-multi-med-notes-ner-gliner_multi-v2.1"

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

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        return self

    # ======================================================
    # Environment setting
    # ======================================================

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
