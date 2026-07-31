import torch
from typing import Any
from .gliner_engine import GlinerEngine

# NOTE: the GLiNER2 engine is not fully implemented yet — disabled until ready.
# from .gliner2_engine import Gliner2Engine
from .llm_engine_huggingface import LLMEngineHuggingFace

def build_engine(engine: str, 
                 model: str, 
                 adapter_model: str | None, 
                 prompt_path: str | None, 
                 use_gpu: bool = True) -> Any:
    # Determine device
    device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
    # Build and return the appropriate engine
    if engine == "gliner":
        return GlinerEngine(model=model,
                            device=device)
    # GLiNER2 engine is not fully implemented yet — disabled until ready.
    # elif engine == "gliner2":
    #     return Gliner2Engine(model=model,
    #                         device=device)
    elif engine == "huggingface":
        return LLMEngineHuggingFace(model=model,
                                    adapter_model=adapter_model,
                                    device=device,
                                    prompts_path=prompt_path)
    else:
        raise ValueError(f"Unknown model type '{engine}'. Use 'gliner' or 'huggingface'.")
__all__ = ["build_engine"]