from typing import List
from gliner import GLiNER

from app.interfaces import Entity
from .base_engine import BaseEngine
from ..utils.text_chunking import trim_medical_text

class GlinerEngine(BaseEngine):
    def __init__(self, 
                 model="urchade/gliner_medium-v2.1", 
                 device="cuda", 
                 labels: list[str] | None = None, 
                 threshold=0.5):
        super().__init__(model=model, device=device)
        self.labels = labels
        self.threshold = threshold
        self._initialize()

    def _initialize(self):
        self.model = GLiNER.from_pretrained(self.model, 
                                            load_tokenizer=False, 
                                            local_files_only=False)
        self.model.to(self.device)

    def extract_entities(self, medical_text: str, labels: list[str]) -> List[Entity]:
        medical_text_chunks = trim_medical_text(medical_text, max_words=300)
        all_entities: List[Entity] = []
        global_offset = 0

        for chunk in medical_text_chunks:
            if not chunk.strip():
                continue
            # 1) Run GLiNER on the chunk
            predictions = self.model.predict_entities(
                chunk,
                labels=labels,
                threshold=self.threshold,
            )
            # 2) Convert local offsets → global offsets
            for p in predictions:
                local_start = int(p["start"])
                local_end = int(p["end"])

                all_entities.append(
                    Entity(
                        text=p["text"],
                        label=p["label"],
                        start=global_offset + local_start,
                        end=global_offset + local_end,
                        score=float(p["score"]) if p["score"] is not None else None,
                    )
                )
            # 3) Move to the next chunk's starting global offset
            global_offset += len(chunk)

        return all_entities
