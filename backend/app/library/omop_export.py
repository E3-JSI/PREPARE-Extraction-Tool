"""OMOP CDM export builder.

Queries mapped data for a dataset, routes concepts to OMOP CDM tables
by domain_id, and packages the result as a ZIP of per-table CSVs.
"""

import csv
import io
import zipfile
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app.models_db import (
    Cluster,
    Concept,
    Dataset,
    Record,
    SourceTerm,
    SourceTermLink,
    SourceToConceptMap,
)

# EHR note type concept
EHR_TYPE_CONCEPT_ID = 32833

# domain_id → OMOP CDM table name
DOMAIN_TABLE: Dict[str, str] = {
    "Condition": "condition_occurrence",
    "Drug": "drug_exposure",
    "Procedure": "procedure_occurrence",
    "Measurement": "measurement",
    "Observation": "observation",
    "Device": "device_exposure",
    "Specimen": "specimen",
    "Visit": "visit_detail",
    "Note": "note",
    "Episode": "episode",
}


def _date_str(dt: object) -> str:
    """Format a datetime/date as YYYY-MM-DD string, or empty."""
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d")
    if isinstance(dt, date):
        return dt.isoformat()
    return str(dt)


def _query_export_rows(
    db: Session,
    dataset_id: int,
    status_filter: Optional[str],
) -> List[dict]:
    """Fetch all mapped source terms with patient/visit/concept data."""
    LinkedTerm = aliased(SourceTerm)
    LinkedCluster = aliased(Cluster)

    statement = (
        select(SourceTerm, Record, Concept, SourceToConceptMap, LinkedTerm, LinkedCluster)
        .join(Record, SourceTerm.record_id == Record.id)
        .join(Cluster, SourceTerm.cluster_id == Cluster.id)
        .join(SourceToConceptMap, SourceToConceptMap.cluster_id == Cluster.id)
        .join(Concept, SourceToConceptMap.concept_id == Concept.id)
        .outerjoin(SourceTermLink, SourceTermLink.from_term_id == SourceTerm.id)
        .outerjoin(LinkedTerm, SourceTermLink.to_term_id == LinkedTerm.id)
        .outerjoin(LinkedCluster, LinkedTerm.cluster_id == LinkedCluster.id)
        .where(Record.dataset_id == dataset_id)
    )

    if status_filter:
        statement = statement.where(SourceToConceptMap.status == status_filter)

    results = db.exec(statement).all()

    return [
        {
            "source_term_id": st.id,
            "source_term_value": st.value,
            "linked_visit_date": st.linked_visit_date,
            "cluster_id": st.cluster_id,
            "record_id": r.id,
            "patient_id": r.patient_id.strip() if r.patient_id else r.patient_id,
            "visit_date": r.visit_date,
            "record_text": r.text,
            "vocab_term_id": c.vocab_term_id,
            "domain_id": c.domain_id,
            "vocab_term_name": c.vocab_term_name,
            "mapping_status": m.status,
            "linked_value": (lc.title if lc else lt.value) if lt else None,
        }
        for st, r, c, m, lt, lc in results
    ]


def _write_csv(rows: List[List], columns: List[str]) -> str:
    """Write rows to a CSV string with given column headers."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    writer.writerows(rows)
    return buf.getvalue()


def build_omop_cdm_zip(
    dataset: Dataset,
    db: Session,
    status_filter: Optional[str] = None,
) -> Tuple[bytes, str]:
    """Build an OMOP CDM ZIP containing per-table CSVs.

    Args:
        dataset: The Dataset to export.
        db: Database session.
        status_filter: Optional mapping status filter.

    Returns:
        Tuple of (zip_bytes, filename).
    """
    rows = _query_export_rows(db, dataset.id, status_filter)

    # ----- Build lookup maps -----
    # Use actual patient_id from database records
    unique_patients: set = set()
    # (patient_id, date) → visit_occurrence_id
    visit_keys: Dict[Tuple[str, Optional[str]], int] = {}
    # patient_id → list of dates
    patient_dates: Dict[str, List[Optional[datetime]]] = defaultdict(list)

    for row in rows:
        pid = row["patient_id"]
        unique_patients.add(pid)

        resolved_date = row["linked_visit_date"] or row["visit_date"]
        patient_dates[pid].append(resolved_date)

        visit_key = (pid, _date_str(resolved_date))
        if visit_key not in visit_keys:
            visit_keys[visit_key] = len(visit_keys) + 1

    # ----- Person table -----
    person_rows = []
    for pid in sorted(unique_patients):
        person_rows.append([pid, 0, "", 0, 0])
    person_csv = _write_csv(
        person_rows,
        [
            "person_id",
            "gender_concept_id",
            "year_of_birth",
            "race_concept_id",
            "ethnicity_concept_id",
        ],
    )

    # ----- Observation period table -----
    obs_period_rows = []
    obs_id = 0
    for pid in sorted(unique_patients):
        dates = [d for d in patient_dates[pid] if d is not None]
        if not dates:
            continue
        obs_id += 1
        start = _date_str(min(dates))
        end = _date_str(max(dates))
        obs_period_rows.append(
            [obs_id, pid, start, end, EHR_TYPE_CONCEPT_ID]
        )
    obs_period_csv = _write_csv(
        obs_period_rows,
        [
            "observation_period_id",
            "person_id",
            "observation_period_start_date",
            "observation_period_end_date",
            "period_type_concept_id",
        ],
    )

    # ----- Visit occurrence table -----
    visit_rows = []
    for (pid, date_str), visit_id in visit_keys.items():
        visit_rows.append(
            [visit_id, pid, 0, date_str, date_str, EHR_TYPE_CONCEPT_ID]
        )
    visit_csv = _write_csv(
        visit_rows,
        [
            "visit_occurrence_id",
            "person_id",
            "visit_concept_id",
            "visit_start_date",
            "visit_end_date",
            "visit_type_concept_id",
        ],
    )

    # ----- Route clinical rows by domain -----
    domain_rows: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        domain = row["domain_id"]
        domain_rows[domain].append(row)

    csvs: Dict[str, str] = {
        "person.csv": person_csv,
        "observation_period.csv": obs_period_csv,
        "visit_occurrence.csv": visit_csv,
    }

    # ----- Clinical tables -----
    row_id = 0

    # Condition
    if "Condition" in domain_rows:
        table_rows = []
        for r in domain_rows["Condition"]:
            row_id += 1
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            table_rows.append(
                [row_id, r["patient_id"],
                 r["vocab_term_id"], d, EHR_TYPE_CONCEPT_ID]
            )
        csvs["condition_occurrence.csv"] = _write_csv(
            table_rows,
            ["condition_occurrence_id", "person_id",
             "condition_concept_id", "condition_start_date",
             "condition_type_concept_id"],
        )

    # Drug
    if "Drug" in domain_rows:
        table_rows = []
        for r in domain_rows["Drug"]:
            row_id += 1
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            table_rows.append(
                [row_id, r["patient_id"],
                 r["vocab_term_id"], d, EHR_TYPE_CONCEPT_ID]
            )
        csvs["drug_exposure.csv"] = _write_csv(
            table_rows,
            ["drug_exposure_id", "person_id",
             "drug_concept_id", "drug_exposure_start_date",
             "drug_type_concept_id"],
        )

    # Procedure
    if "Procedure" in domain_rows:
        table_rows = []
        for r in domain_rows["Procedure"]:
            row_id += 1
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            table_rows.append(
                [row_id, r["patient_id"],
                 r["vocab_term_id"], d, EHR_TYPE_CONCEPT_ID]
            )
        csvs["procedure_occurrence.csv"] = _write_csv(
            table_rows,
            ["procedure_occurrence_id", "person_id",
             "procedure_concept_id", "procedure_date",
             "procedure_type_concept_id"],
        )

    # Measurement
    if "Measurement" in domain_rows:
        table_rows = []
        for r in domain_rows["Measurement"]:
            row_id += 1
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            lv = r.get("linked_value")
            try:
                value_as_number = float(lv) if lv is not None else None
            except (ValueError, TypeError):
                value_as_number = None
            table_rows.append(
                [row_id, r["patient_id"],
                 r["vocab_term_id"], d, EHR_TYPE_CONCEPT_ID,
                 value_as_number, lv or ""]
            )
        csvs["measurement.csv"] = _write_csv(
            table_rows,
            ["measurement_id", "person_id",
             "measurement_concept_id", "measurement_date",
             "measurement_type_concept_id",
             "value_as_number", "value_source_value"],
        )

    # Observation (domain)
    if "Observation" in domain_rows:
        table_rows = []
        for r in domain_rows["Observation"]:
            row_id += 1
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            lv = r.get("linked_value")
            try:
                value_as_number = float(lv) if lv is not None else None
            except (ValueError, TypeError):
                value_as_number = None
            value_as_string = lv if lv and value_as_number is None else ""
            table_rows.append(
                [row_id, r["patient_id"],
                 r["vocab_term_id"], d, EHR_TYPE_CONCEPT_ID,
                 value_as_number, value_as_string, lv or ""]
            )
        csvs["observation.csv"] = _write_csv(
            table_rows,
            ["observation_id", "person_id",
             "observation_concept_id", "observation_date",
             "observation_type_concept_id",
             "value_as_number", "value_as_string", "value_source_value"],
        )

    # Device
    if "Device" in domain_rows:
        table_rows = []
        for r in domain_rows["Device"]:
            row_id += 1
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            table_rows.append(
                [row_id, r["patient_id"],
                 r["vocab_term_id"], d, EHR_TYPE_CONCEPT_ID]
            )
        csvs["device_exposure.csv"] = _write_csv(
            table_rows,
            ["device_exposure_id", "person_id",
             "device_concept_id", "device_exposure_start_date",
             "device_type_concept_id"],
        )

    # Specimen
    if "Specimen" in domain_rows:
        table_rows = []
        for r in domain_rows["Specimen"]:
            row_id += 1
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            table_rows.append(
                [row_id, r["patient_id"],
                 r["vocab_term_id"], d, EHR_TYPE_CONCEPT_ID]
            )
        csvs["specimen.csv"] = _write_csv(
            table_rows,
            ["specimen_id", "person_id",
             "specimen_concept_id", "specimen_date",
             "specimen_type_concept_id"],
        )

    # Visit Detail (Visit domain)
    if "Visit" in domain_rows:
        table_rows = []
        for r in domain_rows["Visit"]:
            row_id += 1
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            table_rows.append(
                [row_id, r["patient_id"],
                 r["vocab_term_id"], d, d, EHR_TYPE_CONCEPT_ID]
            )
        csvs["visit_detail.csv"] = _write_csv(
            table_rows,
            ["visit_detail_id", "person_id",
             "visit_detail_concept_id", "visit_detail_start_date",
             "visit_detail_end_date", "visit_detail_type_concept_id"],
        )

    # Death
    if "Death" in domain_rows:
        table_rows = []
        for r in domain_rows["Death"]:
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            table_rows.append(
                [r["patient_id"], d, EHR_TYPE_CONCEPT_ID]
            )
        csvs["death.csv"] = _write_csv(
            table_rows,
            ["person_id", "death_date", "death_type_concept_id"],
        )

    # Note
    if "Note" in domain_rows:
        table_rows = []
        for r in domain_rows["Note"]:
            row_id += 1
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            table_rows.append(
                [row_id, r["patient_id"],
                 d, EHR_TYPE_CONCEPT_ID, r["record_text"]]
            )
        csvs["note.csv"] = _write_csv(
            table_rows,
            ["note_id", "person_id", "note_date",
             "note_type_concept_id", "note_text"],
        )

    # Episode
    if "Episode" in domain_rows:
        table_rows = []
        for r in domain_rows["Episode"]:
            row_id += 1
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            table_rows.append(
                [row_id, r["patient_id"],
                 r["vocab_term_id"], d, EHR_TYPE_CONCEPT_ID]
            )
        csvs["episode.csv"] = _write_csv(
            table_rows,
            ["episode_id", "person_id", "episode_concept_id",
             "episode_start_date", "episode_type_concept_id"],
        )

    # ----- Derived era tables -----

    # Condition era
    if "Condition" in domain_rows:
        era_groups: Dict[Tuple[int, str], List[Optional[str]]] = defaultdict(
            list
        )
        for r in domain_rows["Condition"]:
            pid = r["patient_id"]
            cid = r["vocab_term_id"]
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            era_groups[(pid, cid)].append(d)

        era_rows = []
        era_id = 0
        for (pid, cid), dates in era_groups.items():
            non_empty = sorted([d for d in dates if d])
            era_id += 1
            era_rows.append([
                era_id, pid, cid,
                non_empty[0] if non_empty else "",
                non_empty[-1] if non_empty else "",
            ])
        csvs["condition_era.csv"] = _write_csv(
            era_rows,
            ["condition_era_id", "person_id", "condition_concept_id",
             "condition_era_start_date", "condition_era_end_date"],
        )

    # Drug era + Dose era
    if "Drug" in domain_rows:
        drug_era_groups: Dict[Tuple[int, str], List[str]] = defaultdict(list)
        for r in domain_rows["Drug"]:
            pid = r["patient_id"]
            cid = r["vocab_term_id"]
            d = _date_str(r["linked_visit_date"] or r["visit_date"])
            drug_era_groups[(pid, cid)].append(d)

        era_rows = []
        dose_rows = []
        era_id = 0
        dose_id = 0
        for (pid, cid), dates in drug_era_groups.items():
            non_empty = sorted([d for d in dates if d])
            era_id += 1
            era_rows.append([
                era_id, pid, cid,
                non_empty[0] if non_empty else "",
                non_empty[-1] if non_empty else "",
            ])
            dose_id += 1
            dose_rows.append([
                dose_id, pid, cid, "",
                non_empty[0] if non_empty else "",
                non_empty[-1] if non_empty else "",
            ])
        csvs["drug_era.csv"] = _write_csv(
            era_rows,
            ["drug_era_id", "person_id", "drug_concept_id",
             "drug_era_start_date", "drug_era_end_date"],
        )
        csvs["dose_era.csv"] = _write_csv(
            dose_rows,
            ["dose_era_id", "person_id", "drug_concept_id",
             "dose_value", "dose_era_start_date", "dose_era_end_date"],
        )

    # ----- Package into ZIP -----
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, csv_content in csvs.items():
            zf.writestr(filename, csv_content)

    zip_buf.seek(0)
    safe_name = dataset.name.replace(" ", "_")
    return zip_buf.getvalue(), f"{safe_name}_omop_cdm.zip"
