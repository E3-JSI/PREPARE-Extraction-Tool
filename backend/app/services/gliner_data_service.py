"""Builds GLiNER training data from reviewed records and their source terms."""

import re
from typing import Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.models_db import Record, SourceTerm


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


def load_reviewed_training_data(
    db: Session,
    dataset_ids: List[int],
    labels: Optional[List[str]] = None,
) -> List[Dict]:
    """Build GLiNER training data from reviewed records across datasets.

    Only records with ``reviewed=True`` are considered. Each source term with
    valid character offsets is mapped onto the record's token sequence and
    emitted as an inclusive ``[start_token, end_token, label]`` triple. Records
    that produce no valid spans are skipped.

    Args:
        db (Session): Active database session.
        dataset_ids (List[int]): Identifiers of the datasets to build training
            data from. Reviewed records across all of them are aggregated.
        labels (Optional[List[str]]): If provided, only source terms whose label
            is in this list are included.

    Returns:
        List[Dict]: A list of ``{"tokenized_text": List[str], "ner": List[List]}``
            training examples.
    """
    if not dataset_ids:
        return []

    records = db.exec(
        select(Record)
        .where(Record.dataset_id.in_(dataset_ids))
        .where(Record.reviewed == True)  # noqa: E712
    ).all()

    if not records:
        return []

    record_ids = [r.id for r in records]

    query = (
        select(SourceTerm)
        .where(SourceTerm.record_id.in_(record_ids))
        .where(SourceTerm.start_position.is_not(None))
        .where(SourceTerm.end_position.is_not(None))
    )

    if labels:
        query = query.where(SourceTerm.label.in_(labels))

    source_terms = db.exec(query).all()

    terms_by_record: Dict[int, List[SourceTerm]] = {}
    for term in source_terms:
        terms_by_record.setdefault(term.record_id, []).append(term)

    training_data: List[Dict] = []

    for record in records:
        text = record.text or ""
        if not text:
            continue

        tokens, spans = tokenize_text_with_spans(text)

        ner: List[List] = []
        for term in terms_by_record.get(record.id, []):
            if (
                term.start_position is None
                or term.end_position is None
                or not term.label
            ):
                continue

            char_start = int(term.start_position)
            char_end = int(term.end_position)

            if char_start < 0 or char_end > len(text) or char_start >= char_end:
                continue

            token_indices = [
                token_idx
                for token_idx, (token_start, token_end) in enumerate(spans)
                if token_start >= char_start and token_end <= char_end
            ]

            if not token_indices:
                continue

            ner.append([token_indices[0], token_indices[-1], term.label])

        if ner:
            training_data.append(
                {
                    "tokenized_text": tokens,
                    "ner": ner,
                }
            )

    return training_data
