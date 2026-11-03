from typing import List, Optional
from pydantic import BaseModel

# =====================================
# Data types
# =====================================

class Entity(BaseModel):
    text: str
    label: str
    start: int
    end: int
    score: Optional[float]

# =====================================
# LitServe interface
# =====================================

class NERRequest(BaseModel):
    medical_text: str
    labels: list[str] | dict[str, str] | None = None

# =====================================
# API interface
# =====================================

class LabelsInput(BaseModel):
    labels: List[str] | None = None