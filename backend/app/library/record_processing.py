from __future__ import annotations

import datetime
from collections import defaultdict
from typing import List, Optional, Sequence, Tuple

import dateparser
from sqlmodel import Session, delete, select

import re

from app.library.sentence_segmenter import iter_sentence_spans
from app.models_db import Dataset, Record, SentenceSegment, SourceTerm


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


def bulk_insert_records_with_segments(db: Session, records: Sequence[Record]) -> None:
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
        if (
            segment.start_offset <= term.start_position
            and end <= segment.end_offset
        ):
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


_MULTI_SPACE = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[,\.;]+$")
_DOT_MONTH = re.compile(r"\b([A-Za-zÄŒÅ Å½ÄÅ¡Å¾]{3,})\.(\b|$)")
_HAS_DIGIT = re.compile(r"\d")

# month/year only: "12/2021", "12-2021", "12.2021"
_MONTH_YEAR_ONLY = re.compile(r"^\s*\d{1,2}\s*[\/\.-]\s*\d{4}\s*$")
_YEAR_ONLY = re.compile(r"^\s*(\d{4})\s*$")

# ISO-like: "2021-12-05" or "2021/12/05"
_ISO_YMD = re.compile(r"^\s*(\d{4})[-/](\d{2})[-/](\d{2})\s*$")
# DMY-like: "5/10/2002", "05-10-2002", "05.10.2002"
_DMY_NUMERIC = re.compile(r"^\s*(\d{1,2})[\/\.-](\d{1,2})[\/\.-](\d{4})\s*$")

_RELATIVE_WORDS = {"today", "yesterday", "tomorrow", "danes", "vÄeraj", "jutri"}
_RELATIVE_WORDS_IT = {
    "oggi",
    "odierna",
    "odierno",
    "ieri",
    "domani",
    "anno fa",
    "anni fa",
}


def _normalize_date_text(s: str) -> str:
    s = s.strip()
    s = _TRAILING_PUNCT.sub("", s)           # remove trailing ",", ".", ";"
    s = _DOT_MONTH.sub(r"\1", s)             # dec. -> dec
    s = s.replace("â€“", "-").replace("â€”", "-")
    s = s.replace("\\", "/")
    s = _MULTI_SPACE.sub(" ", s)
    return s


def _try_parse_iso_ymd(text: str) -> Optional[datetime.datetime]:
    """
    Strictly parse YYYY-MM-DD or YYYY/MM/DD to avoid dateparser flipping.
    """
    m = _ISO_YMD.match(text)
    if not m:
        return None
    y, mo, d = m.group(1), m.group(2), m.group(3)
    try:
        return datetime.datetime(int(y), int(mo), int(d))
    except ValueError:
        return None



def _try_parse_dmy_numeric(text: str) -> Optional[datetime.datetime]:
    """
    Parse DMY numeric formats explicitly to avoid month/day flips.
    """
    m = _DMY_NUMERIC.match(text)
    if not m:
        return None
    d, mo, y = m.group(1), m.group(2), m.group(3)
    try:
        return datetime.datetime(int(y), int(mo), int(d))
    except ValueError:
        return None


def _parse_date_value(value: Optional[str]) -> Optional[datetime.datetime]:
    """
    Fixes:
    - numeric dates parsed as DMY (05.12.2021 -> 2021-12-05)
    - ISO formats parsed strictly (2021-12-05 stays 2021-12-05)
    - blocks relative words (today/yesterday/danes/vÄeraj) to avoid run-date
    - rejects month/year-only (12/2021) to avoid random day completion
    - rejects year-only values (2003) because year is not a full date
    - blocks plain non-numeric words from being interpreted as dates
    - handles 'dec.' style abbreviations
    """
    if not value:
        return None

    text = _normalize_date_text(value)
    if not text:
        return None

    # Block plain text without any number (e.g. "data odierna").
    if _HAS_DIGIT.search(text) is None:
        return None

    lowered = text.lower()

    # 1) Block relative dates
    if any(w in lowered for w in _RELATIVE_WORDS) or any(
        w in lowered for w in _RELATIVE_WORDS_IT
    ):
        return None

    # 2) Block incomplete month/year-only and year-only.
    if _MONTH_YEAR_ONLY.match(text) or _YEAR_ONLY.match(text):
        return None

    # 3) Parse ISO formats strictly first (prevents 2021-12-05 -> 2021-05-12)
    iso_datetime = _try_parse_iso_ymd(text)
    if iso_datetime is not None:
        return iso_datetime

    # 4) Parse DMY numeric explicitly (5/10/2002 -> 5 Oct 2002).
    dmy_datetime = _try_parse_dmy_numeric(text)
    if dmy_datetime is not None:
        return dmy_datetime

    settings = {
        "DATE_ORDER": "DMY",               # main fix for EU numeric formats
        "PREFER_DATES_FROM": "past",
        "RETURN_AS_TIMEZONE_AWARE": False,
        "STRICT_PARSING": True,
    }

    try:
        parsed = dateparser.parse(
            text,
            languages=["sl", "en", "de", "hr", "sr", "ru", "uk", "it"],
            settings=settings,
        )
    except Exception:
        return None

    if parsed is None:
        return None

    if parsed.year < 1900 or parsed.year > 2100:
        return None

    return parsed


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
        # Preserve manually set linked dates
        if not getattr(term, "manual_linked_visit_date", False):
            term.linked_date_term_id = None
            term.linked_visit_date = None
        _ensure_sentence_assignment(term, segments)

    grouped = defaultdict(list)
    for term in terms:
        grouped[term.sentence_segment_id].append(term)

    date_label = dataset.date_label
    fallback_date = record.visit_date

    for segment_id, segment_terms in grouped.items():
        if not date_label:
            for term in segment_terms:
                term.linked_visit_date = fallback_date
            continue

        date_terms: List[Tuple[SourceTerm, Optional[datetime.datetime]]] = []
        for term in segment_terms:
            if term.label == date_label:
                parsed = _parse_date_value(term.value)
                # Do not overwrite manual dates
                if not getattr(term, "manual_linked_visit_date", False):
                    term.linked_visit_date = parsed
                date_terms.append((term, parsed))

        non_date_terms = [t for t in segment_terms if t.label != date_label]

        # Canonical rule:
        # Non-date terms always use record.visit_date.
        # If visit_date is missing, linked date stays empty (No date).
        for entity in non_date_terms:
            if not getattr(entity, "manual_linked_visit_date", False):
                entity.linked_date_term_id = None
                entity.linked_visit_date = fallback_date

    db.flush()

