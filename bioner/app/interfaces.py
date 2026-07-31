from typing import Protocol, List, Dict, Any, TypedDict, Optional
from pydantic import BaseModel

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
    labels: list[str] | None = None
