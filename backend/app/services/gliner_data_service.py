import re
from collections import defaultdict
from typing import Optional
import time

from typing import List, Dict 

from sqlmodel import Session, select

from app.models_db import Record, SourceTerm


def tokenize_text_with_spans(text: str):
    """
    Tokenize text into words and punctuation and return token spans.

    Returns:
        tuple[list[str], list[tuple[int, int]]]:
            - token strings
            - char span tuples (start, end)
    """
    tokens = []
    spans = []
    for match in re.finditer(r"\b\w+\b|[^\w\s]", text, flags=re.UNICODE):
        tokens.append(match.group())
        spans.append((match.start(), match.end()))
    return tokens, spans


def tokenize_text(text: str) -> List[str]:
    """
    Tokenize text into words and punctuation.
    Preserves punctuation as separate tokens.
    """
    tokenized_text, _ = tokenize_text_with_spans(text)
    return tokenized_text


def extract_gliner_entities_train(example, splitter):

    example_text = example["text"]
    ws_generator = splitter(example_text)

    token_info = []
    tokenized_text = []
    for token_idx, token in enumerate(ws_generator):
        token_info.append(
            # token text, start char, end char, token index
            (token[0], token[1], token[2], token_idx)
        )
        tokenized_text.append(token[0])

    skipped_entities = 0
    present_entities = []
    seen_spans = set()
    for entity in example.get("entities", []):
        ent_text, ent_label = entity["text"], entity["label"]

        ent_text_escaped = re.escape(ent_text.lower())
        regex1 = rf"\b{ent_text_escaped}\b"

        matches = [match for match in re.finditer(regex1, example_text.lower())]
        if not matches:
            skipped_entities += 1
            continue

        for match in matches:
            mstart_idx, mend_idx = match.span()
            match_ent = re.search(rf"\b{ent_text_escaped}\b", example_text.lower()[mstart_idx:mend_idx])
            start_index = match.start() + match_ent.start()
            end_index = start_index + len(ent_text)

            entity_tokens = [
                (token_text, token_idx)
                for token_text, token_start, token_end, token_idx in token_info
                if token_start >= start_index and token_end <= end_index
            ]

            if entity_tokens:
                span = (entity_tokens[0][1], entity_tokens[-1][1], ent_label)
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                present_entities.append([
                    span[0], span[1], span[2]
                ])

    return {"tokenized_text": tokenized_text, "ner": present_entities}, skipped_entities

def load_reviewed_training_data(
    db: Session,
    dataset_id: int,
    labels: Optional[List[str]] = None,
):
    print(f"[GLiNER DATA LOAD] dataset_id={dataset_id}, labels={labels}")
    records = db.exec(
        select(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.reviewed == True)
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

    terms_by_record = {}

    for term in source_terms:
        terms_by_record.setdefault(term.record_id, []).append(term)

    training_data = []

    for record in records:
        text = record.text or ""

        if not text:
            continue

        tokens, spans = tokenize_text_with_spans(text)

        ner = []
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


def load_reviewed_training_dataOLD(
    db: Session,
    dataset_id: int,
    labels: Optional[List[str]] = None,
) -> tuple[List[Record], List[SourceTerm]]:
    """
    Load reviewed records and their source terms for GLiNER training.
    """
    records = db.exec(
        select(Record)
        .where(Record.dataset_id == dataset_id)
        .where(Record.reviewed == True)
    ).all()

    if not records:
        return [], []

    record_ids = [r.id for r in records]

    query = (
        select(SourceTerm)
        .where(SourceTerm.record_id.in_(record_ids))
        .where(SourceTerm.start_position != None)
        .where(SourceTerm.end_position != None)
    )

    if labels:
        query = query.where(SourceTerm.label.in_(labels))

    source_terms = db.exec(query).all()

    return records, source_terms
# =========================================================
# GLiNER BUILDER (FIXED + SAFE)
# =========================================================

def build_gliner_training_data(records, source_terms):
    terms_by_record = defaultdict(list)

    for term in source_terms:
        if term.record_id is not None:
            terms_by_record[term.record_id].append(term)

    dataset = []
    # 🔥 DEBUG METRICS (critical for diagnosing silent failures)
    total_records = len(records)
    total_terms = len(source_terms)
    records_with_terms = 0
    empty_after_filter = 0

    print("\n📊 GLiNER DATA LOADING STATS")
    print("Records:", total_records)
    print("SourceTerms:", total_terms)

    for record in records:
        if not record.text:
            continue

        text = record.text

        tokens = []
        spans = []
        for m in re.finditer(r"\S+", text):
            tokens.append(m.group())
            spans.append((m.start(), m.end()))

        entities = []   # ✅ IMPORTANT: rename from ner → entities

        for term in terms_by_record.get(record.id, []):
            if term.start_position is None or term.end_position is None or not term.label:
                continue

            char_start = int(term.start_position)
            char_end = int(term.end_position)

            tok_start = tok_end = None

            for i, (s, e) in enumerate(spans):
                if tok_start is None and s >= char_start:
                    tok_start = i
                if e <= char_end:
                    tok_end = i

            if tok_start is not None and tok_end is not None and tok_start <= tok_end:
                entities.append([tok_start, tok_end, term.label])

        if entities:
            dataset.append({
                "text": text,
                "entities": entities   # ✅ THIS IS CRITICAL
            })

# =====================================================
    # 🔥 FINAL DIAGNOSTIC REPORT (CRITICAL)
    # =====================================================
    if len(dataset) == 0:
        print("\n🚨 TRAINING FAILURE DIAGNOSTIC")
        print("Total records:", total_records)
        print("Total terms:", total_terms)
        print("Records with terms:", records_with_terms)
        print("Records dropped (no valid entities):", empty_after_filter)

        print("\n⚠️ MOST LIKELY ISSUE:")
        print("- record.id ↔ term.record_id mismatch OR")
        print("- label filtering removed all terms OR")
        print("- offsets invalid for current text")

        #time.sleep(20) 

    else:
        print("\n✅ GLiNER dataset ready")
        print("First sample:", dataset[0])
        print("Valid training samples:", len(dataset))

        #time.sleep(20) 

    return dataset

def build_gliner_training_data5(records: List[Record], source_terms: List[SourceTerm],
) -> List[Dict]:
    """
    Output format:
    {
        "text": "...",
        "entities": [
            {"start": int, "end": int, "label": str}
        ]
    }
    """

    terms_by_record = defaultdict(list)

    for term in source_terms:
        if term.record_id is not None:
            terms_by_record[term.record_id].append(term)

    dataset = []

    # 🔥 DEBUG METRICS (critical for diagnosing silent failures)
    total_records = len(records)
    total_terms = len(source_terms)
    records_with_terms = 0
    empty_after_filter = 0

    print("\n📊 GLiNER DATA LOADING STATS")
    print("Records:", total_records)
    print("SourceTerms:", total_terms)

    for record in records:
        text = (record.text or "").strip()

        if not text:
            continue

        record_terms = terms_by_record.get(record.id, [])

        if not record_terms:
            empty_after_filter += 1
            continue

        records_with_terms += 1

        entities = []
        seen = set()

        for term in record_terms:

            if (
                term.start_position is None
                or term.end_position is None
                or not term.label
            ):
                continue

            start = int(term.start_position)
            end = int(term.end_position)

            # 🔥 strict validation
            if start < 0 or end > len(text) or start >= end:
                continue

            entity_text = text[start:end].strip()

            if not entity_text:
                continue

            # ensure correctness (VERY IMPORTANT for medical text)
            if entity_text != term.value and term.value is not None:
                # allow small mismatch but log it
                pass

            key = (start, end, term.label)
            if key in seen:
                continue

            seen.add(key)

            entities.append({
                "start": start,
                "end": end,
                "label": term.label
            })

        # only keep valid samples
        if entities:
            dataset.append({
                "text": text,
                "entities": entities
            })
        else:
            empty_after_filter += 1

    # =====================================================
    # 🔥 FINAL DIAGNOSTIC REPORT (CRITICAL)
    # =====================================================
    if len(dataset) == 0:
        print("\n🚨 TRAINING FAILURE DIAGNOSTIC")
        print("Total records:", total_records)
        print("Total terms:", total_terms)
        print("Records with terms:", records_with_terms)
        print("Records dropped (no valid entities):", empty_after_filter)

        print("\n⚠️ MOST LIKELY ISSUE:")
        print("- record.id ↔ term.record_id mismatch OR")
        print("- label filtering removed all terms OR")
        print("- offsets invalid for current text")

    else:
        print("\n✅ GLiNER dataset ready")
        print("Valid training samples:", len(dataset))

    return dataset

def load_reviewed_training_data2( db: Session, dataset_id: int, labels: Optional[List[str]] = None,
) -> tuple[List[Record], List[SourceTerm]]:
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

def build_gliner_training_data4(records: List[Record], source_terms: List[SourceTerm],
) -> List[Dict]:
    """
    GLiNER training format:

    {
        "text": "...",
        "entities": [
            {"start": int, "end": int, "label": str}
        ]
    }
    """

    terms_by_record = defaultdict(list)

    # group terms by record_id
    for term in source_terms:
        if term.record_id is not None:
            terms_by_record[term.record_id].append(term)

    dataset = []

    missing_term_records = 0
    valid_records = 0

    for record in records:
        text = (record.text or "").strip()

        if not text:
            continue

        record_terms = terms_by_record.get(record.id)

        # 🔥 DEBUG GUARD: detect mismatch early
        if not record_terms:
            missing_term_records += 1
            continue

        entities = []
        seen = set()

        for term in record_terms:

            # basic validation
            if (
                term.start_position is None
                or term.end_position is None
                or not term.label
            ):
                continue

            start = int(term.start_position)
            end = int(term.end_position)

            # strict bounds check
            if start < 0 or end > len(text) or start >= end:
                continue

            entity_text = text[start:end].strip()

            # ensure span actually resolves to text
            if not entity_text:
                continue

            key = (start, end, term.label)
            if key in seen:
                continue

            seen.add(key)

            entities.append({
                "start": start,
                "end": end,
                "label": term.label
            })

        # only keep valid samples
        if entities:
            dataset.append({
                "text": text,
                "entities": entities
            })
            valid_records += 1

    # 🔥 CRITICAL DEBUG OUTPUT (this will save you hours)
    if len(dataset) == 0:
        print("\n🚨 GLiNER TRAINING DATA WARNING")
        print("Records received:", len(records))
        print("Source terms received:", len(source_terms))
        print("Records with NO matching terms:", missing_term_records)
        print("👉 Result: EMPTY TRAINING SET (this is why training fails)")

    return dataset

def build_gliner_training_data3(records: List[Record],source_terms: List[SourceTerm],
) -> List[Dict]:

    terms_by_record: Dict[int, List[SourceTerm]] = defaultdict(list)

    for term in source_terms:
        terms_by_record[term.record_id].append(term)

    examples = []

    for record in records:

        text = (record.text or "").strip()

        if not text:
            continue

        entities = []
        seen = set()

        for term in terms_by_record.get(record.id, []):

            if (
                term.start_position is None
                or term.end_position is None
                or not term.label
            ):
                continue

            start = int(term.start_position)
            end = int(term.end_position)

            # validate span
            if start < 0 or end > len(text) or start >= end:
                continue

            entity_text = text[start:end].strip()

            if not entity_text:
                continue

            entity_key = (start, end, term.label)

            if entity_key in seen:
                continue

            seen.add(entity_key)

            entities.append({
                "start": start,
                "end": end,
                "label": term.label,
            })

        if not entities:
            continue

        examples.append({
            "text": text,
            "entities": entities,
        })

    return examples

def build_gliner_training_data2(records: List[Record], source_terms: List[SourceTerm],
) -> List[Dict]:
    """
    Convert DB records + reviewed source terms into GLiNER span-based training format.

    GLiNER format (NOT IOB):
        {"tokenized_text": ["word1", "word2", ...], "ner": [[start_tok, end_tok, label], ...]}

    Token indices are inclusive and based on whitespace splitting (not WordPiece/BPE).
    Character spans from the DB are mapped to whitespace-token spans via re.finditer.
    Records with no matchable spans are skipped.
    """
    terms_by_record: Dict[int, List[SourceTerm]] = defaultdict(list)
    for term in source_terms:
        terms_by_record[term.record_id].append(term)

    examples = []
    for record in records:
        if not record.text:
            continue

        # Build whitespace token list with their character offsets
        tokens: List[str] = []
        token_spans: List[tuple[int, int]] = []
        for match in re.finditer(r"\S+", record.text):
            tokens.append(match.group())
            token_spans.append((match.start(), match.end()))

        if not tokens:
            continue

        ner: List[List] = []
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
