from typing import List
from gliner2 import GLiNER2

from app.interfaces import Entity
from .base_engine import BaseEngine
from ..utils.text_chunking import trim_medical_text

class Gliner2Engine(BaseEngine):
    def __init__(self, 
                 model="fastino/gliner2-base-v1", 
                 device="cuda", 
                 labels: list[str] | dict[str, str] | None = None, 
                 threshold=0.5):
        super().__init__(model=model, device=device)
        self.labels = labels
        self.threshold = threshold
        self._initialize()

    def _initialize(self):
        self.model = GLiNER2.from_pretrained(self.model, 
                                            load_tokenizer=False, 
                                            local_files_only=False)
        self.model.to(self.device)

    def extract_entities(self, medical_text: str, labels: list[str] | dict[str, str]) -> List[Entity]:
        medical_text_chunks = trim_medical_text(medical_text, max_words=300)
        all_entities: List[Entity] = []
        global_offset = 0

        for chunk in medical_text_chunks:
            if not chunk.strip():
                continue

            predictions = self.model.extract_entities(
                chunk,
                labels,
                threshold=self.threshold,
                include_confidence=True,
            )

            entities_dict = predictions.get("entities", {})
            for label, items in entities_dict.items():
                for item in items:
                    local_start = int(item["start"])
                    local_end = int(item["end"])
                    conf = item.get("confidence")

                    all_entities.append(
                        Entity(
                            text=item["text"],
                            label=label,
                            start=global_offset + local_start,
                            end=global_offset + local_end,
                            score=float(conf) if conf is not None else None,
                        )
                    )

            global_offset += len(chunk)

        return all_entities

