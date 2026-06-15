from __future__ import annotations

import datetime
import re
from collections import defaultdict
from typing import List, Optional, Sequence, Tuple

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


def auto_link_entities_for_record(db: Session, record: Record, dataset: Dataset) -> None:
    if not dataset.label_relations:
        return

    relation_map: dict[str, set[str]] = {}
    for rel in dataset.label_relations:
        relation_map.setdefault(rel["from_label"], set()).add(rel["to_label"])

    terms = db.exec(
        select(SourceTerm)
        .where(SourceTerm.record_id == record.id)
        .order_by(SourceTerm.start_position)
    ).all()

    if len(terms) < 2:
        return

    term_ids = [t.id for t in terms]
    existing = {
        (lnk.from_term_id, lnk.to_term_id)
        for lnk in db.exec(
            select(SourceTermLink).where(SourceTermLink.from_term_id.in_(term_ids))
        ).all()
    }

    new_links = []
    for i, term in enumerate(terms[:-1]):
        if term.label not in relation_map:
            continue
        next_term = terms[i + 1]
        if term.sentence_segment_id != next_term.sentence_segment_id:
            continue
        if next_term.label not in relation_map[term.label]:
            continue
        if (term.id, next_term.id) in existing:
            continue
        existing.add((term.id, next_term.id))
        new_links.append(
            SourceTermLink(
                from_term_id=term.id,
                to_term_id=next_term.id,
                dataset_id=dataset.id,
            )
        )

    if new_links:
        db.add_all(new_links)
        db.flush()