from typing import Protocol, List, Dict, Any, TypedDict, Optional
from pydantic import BaseModel, Field

# =====================================
# Data types
# =====================================

class Entity(BaseModel):
    text: str
    label: str
    start: int
    end: int
    score: Optional[float] = None

# =====================================
# LitServe interface
# =====================================

class NERRequest(BaseModel):
    medical_text: str
    labels: list[str] | dict[str, str] | None = None
    include_relations: bool = False
    label_relations: list[dict[str, str]] = Field(default_factory=list)
    date_label: str | None = None
    language: str | None = None
    existing_entities: list[Entity] = Field(default_factory=list)



# Internal clinical models. Defined here as Pydantic contracts.
class Token(BaseModel):
    text: str
    norm: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class SentenceSpan(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    token_start: int = Field(ge=0)
    token_end: int = Field(ge=0)