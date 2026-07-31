import re
import ast
import json
import logging
from app.interfaces import Entity
from typing import Any, List, Dict, Literal, Tuple

logger = logging.getLogger(__name__)

def _coerce_entity_list(parsed: Any) -> List[Dict[str, str]]:
    """Validate that ``parsed`` is a list of dicts.

    Returns the list unchanged on success, or ``None`` if the shape is wrong so
    callers can keep trying other parsing strategies.
    """
    if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        return parsed
    return None

def _loads_tolerant(fragment: str) -> List[Dict[str, str]]:
    """Parse a JSON-ish fragment without mangling apostrophes.

    Tries strict JSON first, then ``ast.literal_eval`` for Python-style /
    single-quoted payloads (which correctly handles apostrophes inside string
    values, e.g. ``Crohn's disease``). Returns a validated list of dicts, or
    ``None`` if nothing usable could be parsed.
    """
    fragment = fragment.strip()
    if not fragment:
        return None
    # Strict JSON (double-quoted) first.
    try:
        return _coerce_entity_list(json.loads(fragment))
    except (json.JSONDecodeError, ValueError):
        pass
    # Python literal / single-quoted: ast.literal_eval understands embedded
    # apostrophes inside quoted strings, unlike a blind quote swap.
    try:
        return _coerce_entity_list(ast.literal_eval(fragment))
    except (ValueError, SyntaxError):
        pass
    return None

def parse_response(response: str) -> List[Dict[str, str]]:
    """Parse the response from the LLM.

    Args:
        response: The response to parse.

    Returns:
        The parsed response: a list of entity dicts (possibly empty).
    """
    # Try to directly load the whole response.
    entities = _loads_tolerant(response)
    if entities is not None:
        return entities

    # Use a regex pattern to find JSON-like structures.
    json_match = re.search(r'\[\s*\{.*?\}\s*\]', response, re.DOTALL)
    if json_match:
        entities = _loads_tolerant(json_match.group())
        if entities is not None:
            return entities

    # Fallback: scan individual lines for a JSON-like array.
    for line in response.splitlines():
        if "[" in line and "{" in line:
            entities = _loads_tolerant(line)
            if entities is not None:
                return entities

    logger.warning("No valid JSON found in the response.")
    return []

def _compile_pattern(entity_text: str, short_word_len: int = 4) -> str:
    """
    Your pattern rule:
      - if <= short_word_len and alphabetic: use word boundaries
      - else: exact escaped match
    """
    if len(entity_text) <= short_word_len and entity_text.isalpha():
        return r'\b{}\b'.format(re.escape(entity_text))
    return re.escape(entity_text)

def find_entity_spans(
    text: str,
    entities: List[Dict[str, str]],
    *,
    short_word_len: int = 4,
    case_insensitive: bool = True,
    deduplicate: bool = False,
    allow_overlaps: bool = False,
    overlap_strategy: Literal["longest", "first"] = "longest",
) -> List[Entity]:
    """
    Convert a list of {'text': ..., 'label': ...} into character spans:
      [{'start': int, 'end': int, 'label': str, 'text': str}, ...]

    Parameters
    ----------
    text : original document text
    entities : list of dicts with keys 'text' and 'label'
    short_word_len : tokens of length <= this and .isalpha() get word-boundary match
    case_insensitive : if True, use re.IGNORECASE
    deduplicate : drop duplicate (start, end, label)
    allow_overlaps : if False, remove overlaps using 'overlap_strategy'
    overlap_strategy : if removing overlaps, keep "longest" (by span width) or "first"
    """
    flags = re.IGNORECASE if case_insensitive else 0
    raw_spans: List[Tuple[int, int, str, str]] = []

    for ent in entities:
        # Degrade gracefully: skip anything that isn't a well-formed entity
        # dict instead of raising and failing the whole NER request.
        if not isinstance(ent, dict):
            continue
        ent_text = ent.get("text")
        ent_label = ent.get("label")
        if not isinstance(ent_text, str) or not isinstance(ent_label, str):
            continue
        pattern = _compile_pattern(ent_text, short_word_len=short_word_len)
        for m in re.finditer(pattern, text, flags=flags):
            start, end = m.start(), m.end()
            # Use the original text slice so casing matches source
            raw_spans.append((start, end, ent_label, text[start:end]))

    # Optional de-duplication
    if deduplicate:
        seen = set()
        deduped = []
        for s in raw_spans:
            key = (s[0], s[1], s[2])
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        raw_spans = deduped

    # Sort by start; when equal, put longer spans first (helps longest strategy)
    raw_spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    if not allow_overlaps:
        kept = []
        if overlap_strategy == "longest":
            # Greedy: go left-to-right; keep a span if it doesn't overlap a kept one
            current_end = -1
            for start, end, label, seg_text in raw_spans:
                if start >= current_end:
                    kept.append((start, end, label, seg_text))
                    current_end = end
                else:
                    # Overlap: since we sorted longer-first per start, skip this shorter one
                    # But if start is the same and end is longer, we already kept the longer one.
                    continue
        elif overlap_strategy == "first":
            # Keep the first one encountered and skip subsequent overlaps
            current_end = -1
            for start, end, label, seg_text in raw_spans:
                if start >= current_end:
                    kept.append((start, end, label, seg_text))
                    current_end = end
                else:
                    continue
        else:
            raise ValueError("overlap_strategy must be 'longest' or 'first'")
        raw_spans = kept
    spans = [
        Entity(
            text=t,
            label=lbl,
            start=s,
            end=e,
            score=None
        )
        for (s, e, lbl, t) in raw_spans
    ]
    return spans
