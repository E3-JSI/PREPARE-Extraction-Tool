import re
from collections import defaultdict
from typing import Optional

from sqlmodel import Session, select

from app.models_db import Record, SourceTerm


def load_reviewed_training_data(
    db: Session,
    dataset_id: int,
    labels: Optional[list[str]] = None,
) -> tuple[list[Record], list[SourceTerm]]:
    """
    Load reviewed records and their source terms for a dataset.

    'Reviewed' means Record.reviewed=True — the clinician has reviewed the note.
    All source terms of a reviewed record with valid character offsets are eligible.
    Labels filter is optional — if provided, only those labels are included.
    """
    records = db.exec(
        select(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.reviewed == True)
    ).all()

    record_ids = [r.id for r in records]
    if not record_ids:
        return [], []

    query = (
        select(SourceTerm)
        .where(SourceTerm.record_id.in_(record_ids))
        .where(SourceTerm.start_position != None)
        .where(SourceTerm.end_position != None)
    )
    if labels:
        query = query.where(SourceTerm.label.in_(labels))

    source_terms = db.exec(query).all()
    return list(records), list(source_terms)


def build_gliner_training_data(
    records: list[Record],
    source_terms: list[SourceTerm],
) -> list[dict]:
    """
    Convert DB records + reviewed source terms into GLiNER span-based training format.

    GLiNER format (NOT IOB):
        {"tokenized_text": ["word1", "word2", ...], "ner": [[start_tok, end_tok, label], ...]}

    Token indices are inclusive and based on whitespace splitting (not WordPiece/BPE).
    Character spans from the DB are mapped to whitespace-token spans via re.finditer.
    Records with no matchable spans are skipped.
    """
    terms_by_record: dict[int, list[SourceTerm]] = defaultdict(list)
    for term in source_terms:
        terms_by_record[term.record_id].append(term)

    examples = []
    for record in records:
        if not record.text:
            continue

        # Build whitespace token list with their character offsets
        tokens: list[str] = []
        token_spans: list[tuple[int, int]] = []
        for match in re.finditer(r"\S+", record.text):
            tokens.append(match.group())
            token_spans.append((match.start(), match.end()))

        if not tokens:
            continue

        ner: list[list] = []
        for term in terms_by_record.get(record.id, []):
            char_start = term.start_position
            char_end = term.end_position

            # Map char span → token span (inclusive)
            tok_start: Optional[int] = None
            tok_end: Optional[int] = None

            for i, (ts, te) in enumerate(token_spans):
                if tok_start is None and ts >= char_start:
                    tok_start = i
                if te <= char_end:
                    tok_end = i

            if tok_start is not None and tok_end is not None and tok_start <= tok_end:
                ner.append([tok_start, tok_end, term.label])

        if ner:
            examples.append({"tokenized_text": tokens, "ner": ner})

    return examples
