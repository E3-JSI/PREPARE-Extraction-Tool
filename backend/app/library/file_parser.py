import io
import csv
import codecs
import json
from collections import defaultdict
from typing import Sequence, Tuple
from pathlib import Path

from dateutil import parser
from datetime import datetime, timezone
import ijson

from fastapi import HTTPException, status

from app.models_db import Record, Concept, Cluster


# ================================================
# Functions to parse uploaded files
# ================================================


def _safe_parse_datetime(value):
    if not value:
        return None

    try:
        parsed = parser.parse(value)

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=timezone.utc)

        return parsed
    except (ValueError, TypeError):
        return None


def parse_records_file(
    file_path: str,
    required_columns: list,
    default_visit_date: datetime | None = None,
):
    """Yield Record objects from the uploaded file lazily."""

    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        for record in parse_csv(
            file_path,
            required_columns,
            default_visit_date=default_visit_date,
        ):
            yield record
        return

    if suffix == ".json":
        for record in parse_json(
            file_path,
            required_columns,
            default_visit_date=default_visit_date,
        ):
            yield record
        return

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported file type.",
    )


def parse_json(
    file_path: str,
    required_columns: list,
    default_visit_date: datetime | None = None,
):
    """Streaming JSON parser – yields Record objects one by one."""

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            items = ijson.items(f, "item")

            for i, obj in enumerate(items):
                if not isinstance(obj, dict):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="JSON array must contain objects.",
                    )

                missing = [col for col in required_columns if col not in obj]
                if missing:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Missing required columns at index {i}: {', '.join(missing)}",
                    )

                visit_candidate = obj.get("visit_date") or obj.get("date")
                visit_date_obj = _safe_parse_datetime(visit_candidate)
                if visit_date_obj is None:
                    visit_date_obj = default_visit_date

                yield Record(
                    patient_id=obj["patient_id"],
                    seq_number=obj.get("seq_number"),
                    text=obj["text"],
                    visit_date=visit_date_obj,
                )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse dataset JSON file: {e}",
        )


def parse_csv(
    file_path: str,
    required_columns: list,
    default_visit_date: datetime | None = None,
):
    """Streaming parser – yields Record objects one by one."""
    try:
        with open(file_path, "rb") as f:
            text_stream = codecs.getreader("utf-8")(f)
            reader = csv.DictReader(text_stream)

            if not reader.fieldnames:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="CSV file is empty or invalid.",
                )

            missing = [col for col in required_columns if col not in reader.fieldnames]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required columns: {', '.join(missing)}",
                )

            for row_number, row in enumerate(reader, start=2):
                if not row.get("text"):
                    continue

                visit_candidate = row.get("visit_date") or row.get("date")
                visit_date_obj = _safe_parse_datetime(visit_candidate)
                if visit_date_obj is None:
                    visit_date_obj = default_visit_date

                try:
                    yield Record(
                        patient_id=row["patient_id"],
                        seq_number=row.get("seq_number"),
                        text=row["text"],
                        visit_date=visit_date_obj,
                    )
                except Exception as row_error:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid data at CSV row {row_number}: {row_error}",
                    )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse dataset CSV file: {e}",
        )


# Will be running in the background
def parse_concepts_file(file_path: str, required_columns: list, unwanted_ids: list):
    """Streaming parser – yields Concept objects one by one."""

    try:
        with open(file_path, "rb") as f:
            text_stream = codecs.getreader("utf-8")(f)
            reader = csv.DictReader(text_stream, delimiter="\t")

            if not reader.fieldnames:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="CSV file is empty or invalid.",
                )

            missing = [c for c in required_columns if c not in reader.fieldnames]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required columns: {', '.join(missing)}",
                )

            for row_number, row in enumerate(reader, start=2):
                vocabulary_name = row.get("vocabulary_id")
                value = row.get("concept_name")
                if (
                    not value
                    or not value.strip()
                    or vocabulary_name in unwanted_ids
                    or not vocabulary_name
                ):
                    continue

                try:
                    concept = Concept(
                        vocab_term_id=row["concept_id"],
                        vocab_term_name=value.strip(),
                        domain_id=row["domain_id"],
                        concept_class_id=row["concept_class_id"],
                        standard_concept=row.get("standard_concept"),
                        concept_code=row.get("concept_code"),
                        valid_start_date=datetime.strptime(
                            row["valid_start_date"], "%Y%m%d"
                        ),
                        valid_end_date=datetime.strptime(
                            row["valid_end_date"], "%Y%m%d"
                        ),
                        invalid_reason=row.get("invalid_reason"),
                    )
                    yield (concept, vocabulary_name)

                except Exception as row_error:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid data at CSV row {row_number}: {row_error}",
                    )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse CSV file: {e}",
        )


# ================================================
# Functions to download files
# ================================================


def download_annotated_dataset(records, format):
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(
            ["patient_id", "seq_number", "visit_date", "entity_type", "entity_name"]
        )
        for record in records:
            for term in record.source_terms:
                entity_type = term.label
                entity_name = (
                    term.cluster.title if term.cluster is not None else term.value
                )
                writer.writerow(
                    [
                        record.patient_id,
                        record.seq_number,
                        record.visit_date,
                        entity_type,
                        entity_name,
                    ]
                )
        output.seek(0)
        return output.getvalue(), "text/csv"

    elif format == "json":
        data = []
        for record in records:
            for term in record.source_terms:
                entity_type = term.label
                entity_name = (
                    term.cluster.title if term.cluster is not None else term.value
                )
                data.append(
                    {
                        "patient_id": record.patient_id,
                        "seq_number": record.seq_number,
                        "visit_date": record.visit_date.isoformat()
                        if record.visit_date
                        else None,
                        "entity_type": entity_type,
                        "entity_name": entity_name,
                    }
                )
        return json.dumps(data), "application/json"

    elif format == "gliner":
        data = []
        for record in records:
            entities = []
            for term in record.source_terms:
                if term.start_position is None or term.end_position is None:
                    continue
                entities.append(
                    {
                        "text": (record.text or "")[
                            term.start_position : term.end_position
                        ]
                        if record.text
                        else term.value,
                        "label": term.label,
                        "start": term.start_position,
                        "end": term.end_position,
                    }
                )
            entities.sort(key=lambda entity: entity["start"])
            data.append({"text": record.text or "", "entities": entities})
        return json.dumps(data, ensure_ascii=False, indent=2), "application/json"

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsuported file format: {format}",
        )


def build_clusters_download_json(
    dataset_name: str,
    clusters: Sequence[Cluster],
    term_rows: Sequence[Tuple[int, str]],
):
    """Create JSON attachment content for dataset clusters."""

    term_map = defaultdict(set)
    for cluster_id, raw_value in term_rows:
        if not raw_value:
            continue
        value = raw_value.strip()
        if value:
            term_map[int(cluster_id)].add(value)

    payload = {
        "clusters": [
            {
                "cluster_name": cluster.title,
                "label": cluster.label,
                "terms": sorted(term_map.get(cluster.id, set())),
            }
            for cluster in clusters
        ]
    }

    safe_name = dataset_name or "dataset"
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    filename = f"{safe_name}_clusters.json"
    return content.encode("utf-8"), filename
