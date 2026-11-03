"""Backend persistence and record-date association.

All GLiNER, lexical enrichment, context inference, and SourceTermLink relation
decisions are performed in bioner. Backend saves the service response only.
"""
from __future__ import annotations

import datetime
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple
from sqlmodel import Session, delete, select
from app.library.sentence_segmenter import iter_sentence_spans
from app.models_db import Dataset, Record, SentenceSegment, SourceTerm, SourceTermLink


_MULTI_SPACE = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[,\.;:]+$")
_HAS_DIGIT = re.compile(r"\d")

_YEAR_ONLY = re.compile(r"^\s*(\d{4})\s*$")
_ISO_YMD = re.compile(r"^\s*(\d{4})[-/](\d{2})[-/](\d{2})\s*$")
_DMY_NUMERIC = re.compile(r"^\s*(\d{1,2})[\/\.-](\d{1,2})[\/\.-](\d{4})\s*$")


def _normalize_date_text(s: str) -> str:
    s = s.strip()
    s = _TRAILING_PUNCT.sub("", s)
    s = s.replace("\\", "/")
    s = _MULTI_SPACE.sub(" ", s)
    return s


def _safe_datetime(year: int, month: int, day: int) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime(year, month, day)
    except Exception:
        return None


def _visit_date_to_datetime(visit_date) -> Optional[datetime.datetime]:
    if visit_date is None:
        return None

    if isinstance(visit_date, datetime.datetime):
        return visit_date.replace(hour=0, minute=0, second=0, microsecond=0)

    if isinstance(visit_date, datetime.date):
        return datetime.datetime.combine(visit_date, datetime.time.min)

    return None


def _clamp_to_visit_date(
    parsed_dt: Optional[datetime.datetime],
    visit_date=None,
) -> Optional[datetime.datetime]:
    if parsed_dt is None:
        return None

    base_dt = _visit_date_to_datetime(visit_date)
    if base_dt is not None and parsed_dt > base_dt:
        return None

    return parsed_dt


def _try_parse_year_only(text: str, visit_date=None) -> Optional[datetime.datetime]:
    match = _YEAR_ONLY.match(text)
    if not match:
        return None

    year = int(match.group(1))
    parsed = _safe_datetime(year, 1, 1)
    return _clamp_to_visit_date(parsed, visit_date)


def _try_parse_iso_ymd(text: str, visit_date=None) -> Optional[datetime.datetime]:
    match = _ISO_YMD.match(text)
    if not match:
        return None

    year, month, day = match.groups()
    parsed = _safe_datetime(int(year), int(month), int(day))
    return _clamp_to_visit_date(parsed, visit_date)


def _try_parse_dmy_numeric(text: str, visit_date=None) -> Optional[datetime.datetime]:
    match = _DMY_NUMERIC.match(text)
    if not match:
        return None

    day, month, year = match.groups()
    parsed = _safe_datetime(int(year), int(month), int(day))
    return _clamp_to_visit_date(parsed, visit_date)


def _parse_date_value(
    value: Optional[str],
    visit_date=None,
) -> Optional[datetime.datetime]:
    if not value:
        return None

    text = _normalize_date_text(value)
    if not text:
        return None

    if _HAS_DIGIT.search(text) is None:
        return None

    parsed = _try_parse_year_only(text, visit_date)
    if parsed is not None:
        return parsed

    parsed = _try_parse_iso_ymd(text, visit_date)
    if parsed is not None:
        return parsed

    parsed = _try_parse_dmy_numeric(text, visit_date)
    if parsed is not None:
        return parsed

    return None


def _build_sentence_segments(record: Record) -> List[SentenceSegment]:
    spans = list(iter_sentence_spans(record.text or ""))
    segments: List[SentenceSegment] = []

    for index, (start, end) in enumerate(spans):
        segments.append(
            SentenceSegment(
                record_id=record.id,
                sequence_index=index,
                start_offset=start,
                end_offset=end,
            )
        )

    if not segments and record.text:
        segments.append(
            SentenceSegment(
                record_id=record.id,
                sequence_index=0,
                start_offset=0,
                end_offset=len(record.text),
            )
        )

    return segments


def bulk_insert_records_with_segments(
    db: Session,
    records: Sequence[Record],
) -> None:
    if not records:
        return

    db.bulk_save_objects(records, return_defaults=True)
    db.flush()

    segments: List[SentenceSegment] = []
    for record in records:
        if record.id is None:
            continue
        segments.extend(_build_sentence_segments(record))

    if segments:
        db.bulk_save_objects(segments, return_defaults=True)

    db.commit()


def regenerate_record_segments(db: Session, record: Record) -> None:
    db.exec(delete(SentenceSegment).where(SentenceSegment.record_id == record.id))

    segments = _build_sentence_segments(record)
    if segments:
        db.bulk_save_objects(segments, return_defaults=True)

    db.flush()


def _ensure_sentence_assignment(
    term: SourceTerm,
    segments: Sequence[SentenceSegment],
) -> None:
    if term.sentence_segment_id is not None:
        return

    if term.start_position is None:
        return

    end = term.end_position if term.end_position is not None else term.start_position
    for segment in segments:
        if segment.start_offset <= term.start_position and end <= segment.end_offset:
            term.sentence_segment_id = segment.id
            return


def _term_midpoint(
    term: SourceTerm,
    segment_lookup: dict[int | None, SentenceSegment],
) -> float:
    start = term.start_position
    end = term.end_position

    if start is None or end is None:
        segment = segment_lookup.get(term.sentence_segment_id)
        if segment:
            if start is None:
                start = segment.start_offset
            if end is None:
                end = segment.end_offset

    if start is None:
        start = 0
    if end is None:
        end = start

    return (start + end) / 2.0


def link_dates_for_record(
    db: Session,
    record: Record,
    dataset: Optional[Dataset] = None,
) -> None:
    dataset = dataset or record.dataset
    if dataset is None:
        dataset = db.get(Dataset, record.dataset_id)
        if dataset is None:
            return

    terms = db.exec(select(SourceTerm).where(SourceTerm.record_id == record.id)).all()
    if not terms:
        return

    segments = db.exec(
        select(SentenceSegment)
        .where(SentenceSegment.record_id == record.id)
        .order_by(SentenceSegment.sequence_index)
    ).all()

    if not segments and record.text:
        regenerate_record_segments(db, record)
        segments = db.exec(
            select(SentenceSegment)
            .where(SentenceSegment.record_id == record.id)
            .order_by(SentenceSegment.sequence_index)
        ).all()

    segment_lookup = {segment.id: segment for segment in segments}

    for term in terms:
        if not getattr(term, "manual_linked_visit_date", False):
            term.linked_date_term_id = None
            term.linked_visit_date = None
        _ensure_sentence_assignment(term, segments)

    grouped = defaultdict(list)
    for term in terms:
        grouped[term.sentence_segment_id].append(term)

    date_label = dataset.date_label
    fallback_date = _visit_date_to_datetime(record.visit_date)

    for _, segment_terms in grouped.items():
        if not date_label:
            for term in segment_terms:
                if not getattr(term, "manual_linked_visit_date", False):
                    term.linked_visit_date = fallback_date
            continue

        date_terms: List[Tuple[SourceTerm, Optional[datetime.datetime]]] = []
        for term in segment_terms:
            if term.label == date_label:
                parsed = _parse_date_value(term.value, fallback_date)

                if not getattr(term, "manual_linked_visit_date", False):
                    term.linked_visit_date = parsed

                date_terms.append((term, parsed))

        non_date_terms = [term for term in segment_terms if term.label != date_label]
        valid_dates = [(term, dt) for term, dt in date_terms if dt is not None]

        if len(valid_dates) == 1:
            date_term, parsed_dt = valid_dates[0]
            for entity in non_date_terms:
                if not getattr(entity, "manual_linked_visit_date", False):
                    entity.linked_date_term_id = date_term.id
                    entity.linked_visit_date = parsed_dt

        elif len(valid_dates) > 1:
            date_midpoints = {
                date_term.id: _term_midpoint(date_term, segment_lookup)
                for date_term, _ in valid_dates
            }

            for entity in non_date_terms:
                entity_mid = _term_midpoint(entity, segment_lookup)
                closest_term_id = None
                closest_dt = None
                closest_distance = None

                for date_term, parsed_dt in valid_dates:
                    midpoint = date_midpoints[date_term.id]
                    distance = abs(entity_mid - midpoint)

                    if closest_distance is None or distance < closest_distance:
                        closest_distance = distance
                        closest_term_id = date_term.id
                        closest_dt = parsed_dt

                if not getattr(entity, "manual_linked_visit_date", False):
                    entity.linked_date_term_id = closest_term_id
                    entity.linked_visit_date = closest_dt

        else:
            for entity in non_date_terms:
                if not getattr(entity, "manual_linked_visit_date", False):
                    entity.linked_visit_date = fallback_date

    db.flush()


def _normalized_label(label: Optional[str]) -> str:
    return (label or "").strip().casefold()


def _label_prompt(label: str) -> str:
    """Convert dataset labels into GLiNER-friendly prompts."""
    return " ".join(
        str(label)
        .replace("_", " ")
        .replace("-", " ")
        .strip()
        .casefold()
        .split()
    )


def _collect_labels_from_config(value: Any) -> List[str]:
    """Extract labels from different possible dataset config shapes."""
    labels: List[str] = []

    if value is None:
        return labels

    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            labels.append(stripped)
        return labels

    if isinstance(value, dict):
        for key in (
            "label",
            "name",
            "value",
            "from_label",
            "to_label",
        ):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                labels.append(item.strip())

        for key in (
            "labels",
            "entity_labels",
            "label_names",
            "items",
            "options",
        ):
            labels.extend(_collect_labels_from_config(value.get(key)))

        return labels

    if isinstance(value, (list, tuple, set)):
        for item in value:
            labels.extend(_collect_labels_from_config(item))
        return labels

    return labels


def _dataset_gliner_label_map(dataset: Dataset) -> dict[str, str]:
    label_map: dict[str, str] = {}

    def add_label(label: Optional[str]) -> None:
        if not label:
            return

        storage_label = str(label).strip()
        if not storage_label:
            return

        prompt = _label_prompt(storage_label)
        if not prompt:
            return

        label_map.setdefault(prompt, storage_label)

    for relation in getattr(dataset, "label_relations", None) or []:
        if isinstance(relation, dict):
            add_label(relation.get("from_label"))
            add_label(relation.get("to_label"))

    for attr_name in (
        "labels",
        "entity_labels",
        "label_names",
        "label_config",
        "annotation_labels",
        "source_labels",
    ):
        for label in _collect_labels_from_config(getattr(dataset, attr_name, None)):
            add_label(label)

    return label_map


def _storage_label(
    entity_label: str,
    dataset: Dataset,
    configured_labels: Optional[dict[str, str]] = None,
) -> str:
    """Keep the EXACT user spelling/case for configured entity labels."""
    if entity_label == "DATE" and getattr(dataset, "date_label", None):
        return dataset.date_label
    if configured_labels is None:
        configured_labels = {
            _normalized_label(label): label
            for label in _dataset_gliner_label_map(dataset).values()
        }
    return configured_labels.get(_normalized_label(entity_label), entity_label)


def _get_or_create_pipeline_terms(
    db: Session,
    record: Record,
    dataset: Dataset,
    entities: Sequence[Dict[str, Any]],
    segments: Sequence[SentenceSegment],
    requested_labels: Sequence[str] = (),
) -> tuple[dict[str, SourceTerm], int]:
    """Merge pipeline entities into the existing SourceTerm table."""
    existing_terms = db.exec(
        select(SourceTerm)
        .where(SourceTerm.record_id == record.id)
        .order_by(SourceTerm.start_position)
    ).all()

    by_exact_span: dict[tuple[int, int, str], SourceTerm] = {}
    for term in existing_terms:
        if term.start_position is None or term.end_position is None:
            continue
        by_exact_span[
            (
                term.start_position,
                term.end_position,
                _normalized_label(term.label),
            )
        ] = term

    # The database stores dataset-defined labels, not arbitrary intermediate
    # clinical categories such as NEGATION or UNIT unless explicitly requested.
    configured_labels = {
        _normalized_label(label): label
        for label in _dataset_gliner_label_map(dataset).values()
    }
    for requested_label in requested_labels:
        if requested_label:
            configured_labels.setdefault(_normalized_label(requested_label), requested_label)
    date_label = getattr(dataset, "date_label", None)
    if date_label:
        configured_labels[_normalized_label(date_label)] = date_label
    allowed_labels = set(configured_labels)
    entity_map: dict[str, SourceTerm] = {}
    new_terms: List[SourceTerm] = []

    for entity in entities:
        pipeline_id = entity.get("id")
        start = entity.get("start")
        end = entity.get("end")
        raw_label = entity.get("label")
        value = entity.get("text")

        if (
            not pipeline_id
            or start is None
            or end is None
            or not raw_label
            or not value
        ):
            continue

        label = _storage_label(str(raw_label), dataset, configured_labels)
        if _normalized_label(label) not in allowed_labels:
            continue
        key = (int(start), int(end), _normalized_label(label))
        source_term = by_exact_span.get(key)

        if source_term is None:
            kwargs: Dict[str, Any] = {
                "record_id": record.id,
                "value": value,
                "label": label,
                "start_position": int(start),
                "end_position": int(end),
            }

            # Both fields are real columns of app.models_db.SourceTerm.
            # Never write computed context metadata that this table cannot store.
            kwargs["automatically_extracted"] = True
            if entity.get("score") is not None:
                kwargs["score"] = entity["score"]

            source_term = SourceTerm(**kwargs)
            _ensure_sentence_assignment(source_term, segments)
            new_terms.append(source_term)
            by_exact_span[key] = source_term
        else:
            # Protect the user's manually-created annotations from a pipeline
            # that happens to predict the same text span and label.
            is_manual = not source_term.automatically_extracted
            if is_manual:
                entity_map[str(pipeline_id)] = source_term
                continue
            if entity.get("score") is not None:
                source_term.score = entity["score"]
            _ensure_sentence_assignment(source_term, segments)

        entity_map[str(pipeline_id)] = source_term

    if new_terms:
        db.add_all(new_terms)

    db.flush()
    return entity_map, len(new_terms)


def _save_pipeline_relations(
    db: Session,
    dataset: Dataset,
    entity_map: dict[str, SourceTerm],
    relations: Sequence[Dict[str, Any]],
) -> None:
    """Store only relations compatible with the existing SourceTermLink table.

    SourceTermLink has no relation_type/source/score or auto marker: persisting
    arbitrary clinical relation types as generic 'has value' edges would
    silently change their meaning in the frontend. Only configured directed
    dataset label relations are valid here.
    """
    allowed_pairs = {
        (_normalized_label(rel.get("from_label")), _normalized_label(rel.get("to_label")))
        for rel in (getattr(dataset, "label_relations", None) or [])
        if isinstance(rel, dict) and rel.get("from_label") and rel.get("to_label")
    }
    if not allowed_pairs:
        return

    mapped_term_ids = [term.id for term in entity_map.values() if term.id is not None]
    if not mapped_term_ids:
        return

    existing = {
        (link.from_term_id, link.to_term_id)
        for link in db.exec(
            select(SourceTermLink).where(SourceTermLink.from_term_id.in_(mapped_term_ids))
        ).all()
    }
    new_links: List[SourceTermLink] = []

    for relation in relations:
        head = entity_map.get(str(relation.get("head")))
        tail = entity_map.get(str(relation.get("tail")))
        if head is None or tail is None or head.id is None or tail.id is None:
            continue
        if head.id == tail.id:
            continue
        if (_normalized_label(head.label), _normalized_label(tail.label)) not in allowed_pairs:
            continue
        key = (head.id, tail.id)
        if key in existing:
            continue
        new_links.append(
            SourceTermLink(
                from_term_id=head.id,
                to_term_id=tail.id,
                dataset_id=dataset.id,
            )
        )
        existing.add(key)

    if new_links:
        db.add_all(new_links)
        db.flush()




def service_label_map(dataset: Dataset, requested_labels: Optional[Sequence[str]] = None) -> dict[str, str]:
    """GLiNER prompts -> exact user-visible labels; date always available."""
    if requested_labels:
        result = {
            _label_prompt(label): label
            for label in requested_labels if label and _label_prompt(label)
        }
    else:
        result = _dataset_gliner_label_map(dataset)
    if dataset.date_label:
        result.setdefault(_label_prompt(dataset.date_label), dataset.date_label)
    return result


def existing_manual_entities(db: Session, record: Record) -> list[dict]:
    """Expose manual annotations with valid source offsets to the BioNER service.

    This lets the service preserve the original dataset-link fallback which
    considered manually annotated SourceTerms, without moving DB access there.
    """
    text = record.text or ""
    manual = db.exec(select(SourceTerm).where(
        SourceTerm.record_id == record.id,
        SourceTerm.automatically_extracted == False,  # noqa: E712
    )).all()
    result = []
    for term in manual:
        start, end = term.start_position, term.end_position
        if start is None or end is None or not (0 <= start < end <= len(text)):
            continue
        result.append({"text": text[start:end], "label": term.label,
                       "start": start, "end": end, "score": term.score})
    return result


def save_service_response(db: Session, record: Record, dataset: Dataset,
                          result: dict,
                          requested_labels: Sequence[str] = ()) -> int:
    """Persist remote entities and typed link decisions; never invoke inference.

    Existing clinical relation types not supported by SourceTermLink are not
    persisted unless the dataset explicitly configures their label pair.
    """
    if record.id is None:
        return 0
    segments = db.exec(select(SentenceSegment).where(
        SentenceSegment.record_id == record.id
    ).order_by(SentenceSegment.sequence_index)).all()
    if not segments and record.text:
        regenerate_record_segments(db, record)
        segments = db.exec(select(SentenceSegment).where(
            SentenceSegment.record_id == record.id
        ).order_by(SentenceSegment.sequence_index)).all()
    mapping, added = _get_or_create_pipeline_terms(
        db, record, dataset, result.get("entities", []), segments, requested_labels
    )
    _save_pipeline_relations(db, dataset, mapping, result.get("relations", []))
    link_dates_for_record(db, record, dataset)
    return added