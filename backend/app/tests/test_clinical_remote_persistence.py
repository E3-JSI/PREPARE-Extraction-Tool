"""Remote clinical extraction contract and SourceTerm persistence (requires SQLModel)."""
import pytest
from sqlmodel import select

from app.library.record_processing import (
    existing_manual_entities, save_service_response, service_label_map,
)
from app.models_db import SourceTerm, SourceTermLink
from app.services import bioner_client


def _result(text="Aspirin 5 mg"):
    return {
        "entities": [
            {"id": "T1", "text": "Aspirin", "label": "Drug", "start": 0, "end": 7, "score": 0.9},
            {"id": "T2", "text": "5", "label": "Value", "start": 8, "end": 9},
            {"id": "T3", "text": "mg", "label": "UNIT", "start": 10, "end": 12},
        ],
        "relations": [
            {"head": "T1", "tail": "T2", "type": "CONFIGURED"},
            {"head": "T1", "tail": "T3", "type": "HAS_UNIT"},
        ],
    }


def test_persists_only_dataset_links_and_auto_terms(session, sample_dataset, sample_record):
    sample_dataset.labels = ["Drug", "Value"]
    sample_dataset.label_relations = [{"from_label": "Drug", "to_label": "Value"}]
    sample_record.text = "Aspirin 5 mg"
    session.add_all([sample_dataset, sample_record])
    session.flush()
    count = save_service_response(session, sample_record, sample_dataset, _result())
    assert count == 2
    terms = session.exec(select(SourceTerm).where(SourceTerm.record_id == sample_record.id)).all()
    assert {(t.label, t.value) for t in terms} == {("Drug", "Aspirin"), ("Value", "5")}
    assert all(t.automatically_extracted for t in terms)
    links = session.exec(select(SourceTermLink)).all()
    assert len(links) == 1
    by_id = {t.id:t for t in terms}
    assert (by_id[links[0].from_term_id].label, by_id[links[0].to_term_id].label) == ("Drug", "Value")
    assert save_service_response(session, sample_record, sample_dataset, _result()) == 0
    assert len(session.exec(select(SourceTermLink)).all()) == 1


def test_manual_term_protected_and_used_by_service(session, sample_dataset, sample_record):
    sample_dataset.labels=["Drug", "Value"]
    sample_dataset.label_relations=[{"from_label":"Drug","to_label":"Value"}]
    sample_record.text="Aspirin 5 mg"
    session.add_all([sample_record,sample_dataset])
    session.flush()
    manual=SourceTerm(record_id=sample_record.id,value="Aspirin",label="Drug",
                      start_position=0,end_position=7,automatically_extracted=False)
    session.add(manual)
    session.flush()
    manual_id=manual.id
    assert existing_manual_entities(session,sample_record)[0]["label"] == "Drug"
    assert save_service_response(session,sample_record,sample_dataset,_result()) == 1
    session.refresh(manual)
    assert manual.id==manual_id and manual.automatically_extracted is False


def test_user_labels_never_silently_renamed(session,sample_dataset,sample_record):
    sample_dataset.labels=["Custom_Diagnosis"]
    sample_record.text="asthma"
    session.add_all([sample_dataset,sample_record])
    session.flush()
    assert service_label_map(sample_dataset)=={"custom diagnosis":"Custom_Diagnosis"}
    result={"entities":[{"id":"T1","label":"Custom_Diagnosis","text":"asthma",
                         "start":0,"end":6}],"relations":[]}
    assert save_service_response(session,sample_record,sample_dataset,result)==1
    term=session.exec(select(SourceTerm).where(SourceTerm.record_id==sample_record.id)).one()
    assert term.label == "Custom_Diagnosis"


def test_client_sends_new_contract_and_checks_ids(monkeypatch):
    posted = {}
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"entities":[{"id":"T1","text":"aspirin","start":0,"end":7,"label":"Drug"}],
                    "relations":[]}
    def fake_post(url, **kwargs):
        posted.update(kwargs)
        return Response()
    monkeypatch.setattr(bioner_client.requests,"post",fake_post)
    result=bioner_client.extract_with_relations("aspirin",{"drug":"Drug"},[],None)
    assert result["entities"][0]["id"]=="T1"
    assert posted["json"]["include_relations"] is True
    assert posted["json"]["labels"]=={"drug":"Drug"}


def test_old_bioner_response_fails_loudly(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return [{"text":"aspirin","start":0,"end":7,"label":"Drug"}]
    monkeypatch.setattr(bioner_client.requests,"post",lambda *a,**k: Response())
    with pytest.raises(bioner_client.InvalidNERResponse):
        bioner_client.extract_with_relations("aspirin",["drug"],[],None)
