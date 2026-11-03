"""Regression tests for the full post-NER logic moved from backend to BioNER.

These do not download model weights: predicted entities are supplied explicitly.
"""
from __future__ import annotations

import pytest

from app.library.clinical_relations import (
    ClinicalTokenizer, EntityContextClassifier, ImprovedClinicalPipeline,
    TokenLexicalEnricher,
)


def predicted(text, substring, label):
    start = text.index(substring)
    return {"text": substring, "label": label, "start": start, "end": start+len(substring), "score": 0.95}


@pytest.fixture
def pipeline():
    return ImprovedClinicalPipeline(use_context_classifier=False)


@pytest.mark.parametrize("text", [".", ",", "/", "...", "--", "", ".5", "5."])
def test_number_validation_rejects_punctuation_and_incomplete_decimal(text):
    assert TokenLexicalEnricher._is_number_text(text) is False


@pytest.mark.parametrize("text", ["37", "37.5", "37,5", "12345"])
def test_number_validation_accepts_real_numbers(text):
    assert TokenLexicalEnricher._is_number_text(text) is True


def test_punctuation_not_value(pipeline):
    out = pipeline.run("Aspirin taken.", [predicted("Aspirin taken.", "Aspirin", "drug")])
    assert not any(ent["label"] == "VALUE" and ent["text"] == "." for ent in out["entities"])


def test_sentences_keep_dotted_dates_and_decimals():
    text = "Temperatur 37.5 C am 12.05.2020. Patient well."
    tok = ClinicalTokenizer()
    tokens = tok.tokenize(text)
    assert len(tok.split_sentences(text, tokens)) == 2


def test_dotted_date_and_decimal_are_extracted(pipeline):
    text = "Temperatur 37.5 C am 12.05.2020."
    out = pipeline.run(text, [predicted(text, "Temperatur", "measurement")])
    assert ("37.5", "VALUE") in {(e["text"], e["label"]) for e in out["entities"]}
    assert ("12.05.2020", "DATE") in {(e["text"], e["label"]) for e in out["entities"]}
    for rel_type in ("HAS_VALUE", "HAS_DATE"):
        assert any(r["type"] == rel_type for r in out["relations"])


def test_invalid_calendar_dates_not_extracted(pipeline):
    out = pipeline.run("Temperature 37.2 on 31.02.2020.", [])
    assert not any(e["label"] == "DATE" for e in out["entities"])


def test_known_not_negated(pipeline):
    text = "Patient has known asthma."
    out = pipeline.run(text, [predicted(text, "asthma", "condition")])
    ent = next(e for e in out["entities"] if e["text"] == "asthma" and e["label"] == "condition")
    assert ent["context_class"] != "NEGATED"
    assert "context_score" not in ent


def test_slovenian_bolnik_not_negated(pipeline):
    text = "Bolnik ima astmo."
    out = pipeline.run(text, [predicted(text, "astmo", "condition")], language="sl")
    ent = next(e for e in out["entities"] if e["text"] == "astmo")
    assert ent["context_class"] != "NEGATED"


@pytest.mark.parametrize("text,target,lang", [
    ("No asthma was found.", "asthma", "en"),
    ("Bolnik ni jemal aspirina.", "aspirina", "sl"),
    ("Der Patient hat kein Asthma.", "Asthma", "de"),
    ("Paziente senza asma.", "asma", "it"),
    ("Patiënt zonder astma.", "astma", "nl"),
    ("Ασθενής χωρίς άσθμα.", "άσθμα", "el"),
])
def test_multilingual_negation(pipeline, text, target, lang):
    out = pipeline.run(text, [predicted(text,target,"condition")], language=lang)
    ent = next(e for e in out["entities"] if e["label"]=="condition" and e["text"]==target)
    assert ent["context_class"] == "NEGATED"


def test_uncertain_not_excluded(pipeline):
    text = "Asthma cannot be excluded."
    out = pipeline.run(text, [predicted(text,"Asthma","condition")])
    ent = next(e for e in out["entities"] if e["label"]=="condition")
    assert ent["context_class"] == "UNCERTAIN"


def test_preserves_drug_frequency_and_route(pipeline):
    text = "Aspirin twice daily orally."
    out = pipeline.run(text,[predicted(text,"Aspirin","drug")])
    assert any(e["text"] == "twice daily" and e["label"] == "FREQUENCY" for e in out["entities"])
    assert any(e["text"] == "orally" and e["label"] == "ROUTE" for e in out["entities"])
    assert any(r["type"] == "HAS_FREQUENCY" for r in out["relations"])
    assert any(r["type"] == "HAS_ROUTE" for r in out["relations"])


def test_preserves_duration(pipeline):
    text = "Aspirin for 5 days."
    out = pipeline.run(text,[predicted(text,"Aspirin","drug")])
    assert any(e["text"] == "for 5 days" and e["label"] == "DURATION" for e in out["entities"])
    assert any(r["type"] == "HAS_DURATION" for r in out["relations"])


def test_configured_nearest_left_value(pipeline):
    text = "37.5 Temperature"
    out = pipeline.run(text,[predicted(text,"Temperature","measurement")],
                       label_relations=[{"from_label":"measurement","to_label":"VALUE"}])
    by_id={e["id"]:e for e in out["entities"]}
    assert any(by_id[r["head"]]["text"]=="Temperature" and by_id[r["tail"]]["text"]=="37.5" for r in out["relations"])


def test_manual_user_labels_are_preserved(pipeline):
    text="Patient has DiseaseX and detail."
    manual = [predicted(text,"detail","User Custom Label")]
    out = pipeline.run(text,[predicted(text,"DiseaseX","My Diagnosis")],
                       existing_entities=manual, label_relations=[{"from_label":"My Diagnosis", "to_label":"User Custom Label"}])
    assert {e["label"] for e in out["entities"]} >= {"My Diagnosis", "User Custom Label"}
    by_id={e["id"]:e for e in out["entities"]}
    assert any(by_id[r["head"]]["label"] == "My Diagnosis" and by_id[r["tail"]]["label"] == "User Custom Label" for r in out["relations"])


def test_no_cross_sentence_configured_linking(pipeline):
    text="Aspirin. 5 mg."
    out=pipeline.run(text,[predicted(text,"Aspirin","drug")],
                     label_relations=[{"from_label":"drug","to_label":"VALUE"}])
    assert not any(r["type"]=="CONFIGURED" for r in out["relations"])


def test_case_preserving_label_mapping(pipeline):
    text="Paracetamol dose"
    out=pipeline.run(text,[predicted(text,"Paracetamol","drug")],
                     label_map={"drug":"Medication as Entered"})
    assert any(e["label"]=="Medication as Entered" for e in out["entities"])


def test_duplicate_prediction_spans_are_deduplicated(pipeline):
    text="Aspirin 5 mg"
    pred=predicted(text,"Aspirin","drug")
    out=pipeline.run(text,[pred,pred])
    assert sum(e["text"]=="Aspirin" and e["label"]=="drug" for e in out["entities"])==1
