"""Full-service /ner contract with an in-memory fake NER engine (no model download)."""
from app.interfaces import Entity, NERRequest
from app.library.clinical_relations import ImprovedClinicalPipeline
from app.main import NERAPI


class FakeEngine:
    def __init__(self):
        self.calls = 0

    def extract_entities(self, medical_text: str, labels: list[str]):
        self.calls += 1
        start = medical_text.index("Aspirin")
        return [Entity(text="Aspirin", label="drug", start=start, end=start + 7, score=0.9)]


def build_api():
    api = NERAPI(engine="gliner", model="test-model")
    api.model = FakeEngine()
    api.clinical_pipeline = ImprovedClinicalPipeline(use_context_classifier=False)
    api._maybe_swap_model = lambda: None
    return api


def test_legacy_response_is_unchanged():
    api = build_api()
    text = "Aspirin twice daily."
    response = api.predict(api.decode_request(NERRequest(medical_text=text, labels=["drug"])))
    assert isinstance(response, list)
    assert len(response) == 1
    assert api.model.calls == 1


def test_single_inference_full_rules_and_user_labels():
    api = build_api()
    text = "Aspirin twice daily."
    response = api.predict(api.decode_request(NERRequest(
        medical_text=text,
        labels={"drug": "Drug", "frequency": "Frequency"},
        include_relations=True,
        label_relations=[{"from_label": "Drug", "to_label": "Frequency"}],
    )))
    assert api.model.calls == 1
    assert isinstance(response, dict)
    assert any(e["label"] == "Drug" and e["text"] == "Aspirin" for e in response["entities"])
    assert any(e["text"] == "twice daily" and e["label"] == "FREQUENCY" for e in response["entities"])
    assert any(rel["type"] == "HAS_FREQUENCY" for rel in response["relations"])
    assert any(rel["type"] == "CONFIGURED" for rel in response["relations"])
