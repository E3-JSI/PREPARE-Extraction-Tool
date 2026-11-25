"""Builds GLiNER training data from reviewed records and their source terms."""

import re
from typing import Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.models_db import Dataset, Record, SourceTerm


def tokenize_text_with_spans(text: str) -> Tuple[List[str], List[Tuple[int, int]]]:
    """Tokenize text into words and punctuation, returning token character spans.

    Words and standalone punctuation are emitted as separate tokens. Whitespace
    is not emitted as a token.

    Args:
        text (str): The text to tokenize.

    Returns:
        Tuple[List[str], List[Tuple[int, int]]]: A tuple of the token strings and
            their ``(start, end)`` character spans (end is exclusive).
    """
    tokens: List[str] = []
    spans: List[Tuple[int, int]] = []
    for match in re.finditer(r"\b\w+\b|[^\w\s]", text, flags=re.UNICODE):
        tokens.append(match.group())
        spans.append((match.start(), match.end()))
    return tokens, spans


def tokenize_text(text: str) -> List[str]:
    """Tokenize text into words and punctuation.

    Punctuation is preserved as separate tokens.

    Args:
        text (str): The text to tokenize.

    Returns:
        List[str]: The token strings.
    """
    tokens, _ = tokenize_text_with_spans(text)
    return tokens


def _prepare_reviewed_records(
    db: Session,
    records: List[Record],
    labels: Optional[List[str]] = None,
) -> List[Dict]:
    """Convert already-selected reviewed records to GLiNER documents."""
    if not records:
        return []

    selected_record_ids = [record.id for record in records]
    query = select(SourceTerm).where(
        SourceTerm.record_id.in_(selected_record_ids)
    )

    if labels:
        query = query.where(SourceTerm.label.in_(labels))

    terms_by_record: Dict[int, List[SourceTerm]] = {}
    for term in db.exec(query).all():
        terms_by_record.setdefault(term.record_id, []).append(term)

    training_data: List[Dict] = []

    for record in records:
        text = record.text or ""
        if not text.strip():
            continue

        tokens, spans = tokenize_text_with_spans(text)
        if not tokens:
            continue

        token_starts = {
            start: index
            for index, (start, end) in enumerate(spans)
        }
        token_ends = {
            end: index
            for index, (start, end) in enumerate(spans)
        }

        ner: List[List] = []
        valid_record = True

        for term in terms_by_record.get(record.id, []):
            char_start = term.start_position
            char_end = term.end_position

            if (
                char_start is None
                or char_end is None
                or not term.label
                or not term.label.strip()
                or char_start not in token_starts
                or char_end not in token_ends
                or char_start >= char_end
            ):
                valid_record = False
                break

            ner.append(
                [
                    token_starts[char_start],
                    token_ends[char_end],
                    term.label,
                ]
            )

        if not valid_record:
            continue

        ner.sort(key=lambda span: (span[0], span[1], span[2]))

        training_data.append(
            {
                "record_id": record.id,
                "tokenized_text": tokens,
                "ner": ner,
            }
        )

    return training_data


def load_reviewed_training_data(
    db: Session,
    dataset_ids: List[int],
    labels: Optional[List[str]] = None,
) -> List[Dict]:
    """Prepare eligible reviewed documents from selected datasets."""
    if not dataset_ids:
        return []

    records = db.exec(
        select(Record)
        .where(Record.dataset_id.in_(dataset_ids))
        .where(Record.reviewed == True)  # noqa: E712
        .order_by(Record.id)
    ).all()

    return _prepare_reviewed_records(db, records, labels)


def load_reviewed_records_by_ids(
    db: Session,
    record_ids: List[int],
    user_id: int,
    labels: Optional[List[str]] = None,
) -> List[Dict]:
    """Load every saved validation document by its exact record ID."""
    requested_ids = sorted(set(record_ids))
    if not requested_ids:
        return []

    records = db.exec(
        select(Record)
        .join(Dataset, Record.dataset_id == Dataset.id)
        .where(Record.id.in_(requested_ids))
        .where(Record.reviewed == True)  # noqa: E712
        .where(Dataset.user_id == user_id)
        .order_by(Record.id)
    ).all()

    training_data = _prepare_reviewed_records(db, records, labels)
    loaded_ids = {item["record_id"] for item in training_data}

    if loaded_ids != set(requested_ids):
        raise ValueError(
            "Some saved validation documents are missing or no longer eligible."
        )

    return training_data