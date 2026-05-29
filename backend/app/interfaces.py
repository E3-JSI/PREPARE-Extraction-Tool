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
    engine: str | None = None
    model: str | None = None

# =====================================
# API interface
# =====================================

class LabelsInput(BaseModel):
    labels: List[str] | None = None


class SwitchModelRequest(BaseModel):
    engine: str
    model: str
    adapter_model: Optional[str] = None
    use_gpu: bool = False