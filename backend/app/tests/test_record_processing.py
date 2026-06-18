from app.library.record_processing import (
    ImprovedClinicalPipeline,
    _dataset_gliner_label_map,
)
from app.models_db import Dataset


class FakeGLiNER:
    def __init__(self, entities):
        self.entities = entities
        self.calls = []

    def predict_entities(self, text, labels, threshold=0.35, flat_ner=True):
        self.calls.append(
            {
                "text": text,
                "labels": labels,
                "threshold": threshold,
                "flat_ner": flat_ner,
            }
        )
        return list(self.entities)


def _make_pipeline(fake_entities):
    pipeline = ImprovedClinicalPipeline.__new__(ImprovedClinicalPipeline)
    pipeline.gliner = FakeGLiNER(fake_entities)
    return pipeline


def test_dataset_gliner_label_map_collects_dataset_labels_and_relations():
    dataset = Dataset(
        name="Demo dataset",
        labels=["PATIENT_NAME", "DATE", "DRUG"],
        label_relations=[
            {"from_label": "doctor-name", "to_label": "patient identifier"},
            {"from_label": "DRUG", "to_label": "DOSE"},
        ],
        user_id=1,
    )

    label_map = _dataset_gliner_label_map(dataset)

    assert label_map["patient name"] == "PATIENT_NAME"
    assert label_map["doctor name"] == "doctor-name"
    assert label_map["patient identifier"] == "patient identifier"
    assert label_map["drug"] == "DRUG"
    assert label_map["dose"] == "DOSE"
    assert "date" not in label_map


def test_run_ner_uses_extra_dataset_labels_and_maps_back_to_storage_labels():
    pipeline = _make_pipeline(
        [
            {
                "text": "John Smith",
                "label": "patient name",
                "start": 0,
                "end": 10,
                "score": 0.91,
            },
            {
                "text": "John Smith",
                "label": "patient name",
                "start": 0,
                "end": 10,
                "score": 0.91,
            },
            {
                "text": "ibuprofen",
                "label": "drug",
                "start": 26,
                "end": 35,
                "score": 0.95,
            },
        ]
    )

    entities = pipeline.run_ner(
        text="John Smith was prescribed ibuprofen.",
        language="en",
        threshold=0.4,
        extra_label_map={"patient name": "PATIENT_NAME"},
    )

    assert pipeline.gliner.calls
    assert "patient name" in pipeline.gliner.calls[0]["labels"]
    assert len(entities) == 2
    assert entities[0]["label"] == "PATIENT_NAME"
    assert entities[1]["label"] == "DRUG"
