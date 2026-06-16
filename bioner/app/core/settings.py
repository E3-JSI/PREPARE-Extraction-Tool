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
    BIONER_DEFAULT_MODEL: str = "urchade/gliner_small"
    BIONER_DEFAULT_MODEL_PVT: str = "ErikCalcina/synthetic-multi-med-notes-ner-gliner_multi-v2.1"
    BACKEND_URL: str = "http://prepare-backend:8000"
    # ======================================================
    # Environment setting
    # ======================================================

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

settings = Settings()
