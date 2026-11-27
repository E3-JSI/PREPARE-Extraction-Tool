"""Era tables in the OMOP CDM export follow the CDM 30-day persistence window.

Occurrences of the same concept for the same person that are more than 30 days
apart start a new condition_era / drug_era / dose_era row.
"""

import csv
import io
import zipfile
from datetime import datetime

import pytest

from app.library.omop_export import build_omop_cdm_zip
from app.models_db import (
    Cluster,
    Concept,
    Record,
    SourceTerm,
    SourceToConceptMap,
    Vocabulary,
)


def _add_mapped_terms(session, dataset, vocabulary, domain, concept_id, dates):
    concept = Concept(
        vocab_term_id=concept_id,
        vocab_term_name=f"{domain} concept",
        domain_id=domain,
        concept_class_id="Clinical Finding",
        standard_concept="S",
        concept_code=concept_id,
        valid_start_date=datetime(1970, 1, 1),
        valid_end_date=datetime(2099, 12, 31),
        invalid_reason=None,
        vocabulary_id=vocabulary.id,
    )
    cluster = Cluster(label=domain, title=domain, dataset_id=dataset.id)
    session.add_all([concept, cluster])
    session.commit()
    session.add(
        SourceToConceptMap(
            cluster_id=cluster.id, concept_id=concept.id, status="approved"
        )
    )
    for d in dates:
        record = Record(
            patient_id="p1", visit_date=d, text=domain, dataset_id=dataset.id
        )
        session.add(record)
        session.commit()
        session.add(
            SourceTerm(
                value=domain, label=domain, record_id=record.id, cluster_id=cluster.id
            )
        )
    session.commit()


def _read(zip_bytes, name):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return list(csv.DictReader(io.StringIO(zf.read(name).decode())))


@pytest.fixture
def export(session, sample_user, sample_dataset):
    vocabulary = Vocabulary(name="v", user_id=sample_user.id)
    session.add(vocabulary)
    session.commit()
    dates = [
        datetime(2020, 1, 1),
        datetime(2020, 1, 31),  # 30 days later: same era
        datetime(2020, 6, 1),  # 122 days later: new era
    ]
    _add_mapped_terms(session, sample_dataset, vocabulary, "Condition", "201826", dates)
    _add_mapped_terms(session, sample_dataset, vocabulary, "Drug", "1503297", dates)
    zip_bytes, _ = build_omop_cdm_zip(sample_dataset, session)
    return zip_bytes


@pytest.mark.parametrize(
    "table, prefix",
    [
        ("condition_era.csv", "condition_era"),
        ("drug_era.csv", "drug_era"),
        ("dose_era.csv", "dose_era"),
    ],
)
def test_eras_split_on_gaps_over_30_days(export, table, prefix):
    rows = _read(export, table)
    spans = [(r[f"{prefix}_start_date"], r[f"{prefix}_end_date"]) for r in rows]
    assert spans == [("2020-01-01", "2020-01-31"), ("2020-06-01", "2020-06-01")]
    assert [r[f"{prefix}_id"] for r in rows] == ["1", "2"]
