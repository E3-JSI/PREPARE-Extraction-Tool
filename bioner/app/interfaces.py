from typing import Protocol, List, Dict, Any, TypedDict, Optional
from pydantic import BaseModel


class Entity(BaseModel):
    text: str
    label: str
    start: int
    end: int
    score: Optional[float]


class NERRequest(BaseModel):
    medical_text: str
    labels: list[str] | None = None
    engine: str | None = None
    model: str | None = None


class ModelInfo(BaseModel):
    engine: str
    model_path: str
    adapter_model: Optional[str] = None
    prompt_path: Optional[str] = None
    use_gpu: bool
    device: Optional[str] = None
    loaded: bool
    status: str


class ModelHealthCheck(BaseModel):
    healthy: bool
    loaded: bool
    engine: Optional[str] = None
    message: str


class ModelSwitchRequest(BaseModel):
    engine: str
    model: str
    adapter_model: Optional[str] = None
    prompt_path: Optional[str] = None
    use_gpu: bool = False


class AvailableModel(BaseModel):
    name: str
    engine: str
    path: str
    type: str


class AvailableModelsResponse(BaseModel):
    models: List[AvailableModel]
