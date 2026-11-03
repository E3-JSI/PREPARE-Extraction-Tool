import re
from typing import Iterator, Tuple

SEGMENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def iter_sentence_spans(text: str) -> Iterator[Tuple[int, int]]:
    """Yield (start, end) offsets for sentences/segments without modifying text."""
    if not text:
        return

    start = 0
    yielded = False
    for match in SEGMENT_SPLIT_RE.finditer(text):
        end = match.start()
        if end > start:
            yielded = True
            yield (start, end)
        start = match.end()

    if start < len(text):
        yielded = True
        yield (start, len(text))

    if not yielded and text:
        yield (0, len(text))
