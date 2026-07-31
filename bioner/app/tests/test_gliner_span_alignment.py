"""Regression tests for GLiNER training-data span correctness and windowing.

Locks in two fixes:

* ``_clean_items`` must keep token spans INCLUSIVE (no ``+ 1``). GLiNER 0.2.x
  builds candidate spans as ``(start, start + width)`` with ``width`` starting at
  0, so a single-token entity at token ``i`` is the inclusive span ``(i, i)`` and
  the gold lookup is an exact tuple match. A ``+ 1`` trains the model one token
  too wide and silently drops any entity ending on the last token — collapsing
  exact-F1 to ~0.
* ``_window_example`` must trim long records to bounded, span-centred windows
  while preserving multi-span grouping and realigning both token and character
  spans exactly.
"""

from app.core.settings import settings
from app.training.gliner_trainer import GLiNERFinetuner, _window_example


def _finetuner() -> GLiNERFinetuner:
    # Construction does not load a model, so a dummy path is fine.
    return GLiNERFinetuner(run_id=1, base_model_path="x", training_data=[])


def test_clean_items_keeps_inclusive_token_spans():
    """A single-token entity survives as the inclusive span ``(i, i)``."""
    tokens = ["The", "patient", "has", "a", "cold"]
    # "cold" is the last token (index 4); "patient" is a single interior token.
    item = {
        "tokenized_text": tokens,
        "ner": [[1, 1, "SYMPTOM"], [4, 4, "SYMPTOM"]],
    }

    cleaned = _finetuner()._clean_items([item])

    assert len(cleaned) == 1
    out = cleaned[0]

    # Both entities are retained — the last-token one is NOT dropped.
    assert len(out["ner"]) == 2

    for (start, end, _label), (c_start, c_end, _) in zip(out["ner"], out["ner_char"]):
        # Token span is inclusive: slicing [start : end + 1] reproduces the tokens.
        assert out["tokenized_text"][start : end + 1] == tokens[start : end + 1]
        # Char span slices the joined text back to the same surface string.
        assert out["text"][c_start:c_end] == " ".join(tokens[start : end + 1])


def test_clean_items_last_token_entity_not_dropped():
    """An entity ending on the final token must not fail the end-bound guard."""
    tokens = ["fever", "and", "cough"]
    item = {"tokenized_text": tokens, "ner": [[2, 2, "SYMPTOM"]]}

    cleaned = _finetuner()._clean_items([item])

    assert len(cleaned) == 1
    assert cleaned[0]["ner"] == [[2, 2, "SYMPTOM"]]
    start, end, _ = cleaned[0]["ner"][0]
    assert cleaned[0]["tokenized_text"][start : end + 1] == ["cough"]


def test_window_short_example_is_unchanged():
    """A record within budget passes through untouched as a single example."""
    item = {
        "text": "a b c",
        "tokenized_text": ["a", "b", "c"],
        "ner": [[0, 0, "L"]],
        "ner_char": [[0, 1, "L"]],
    }

    out = _window_example(item, max_tokens=256, pad=settings.BIONER_TRAIN_CONTEXT_PAD)

    assert out == [item]


def test_window_keeps_co_occurring_spans_in_one_example():
    """Two spans that fit the budget stay in ONE window, not split per-span."""
    # Pad the record past the budget so windowing actually triggers, but keep the
    # two entities close together so they share a window.
    tokens = ["cold", "and", "headache"] + ["filler"] * 300
    item = {
        "text": " ".join(tokens),
        "tokenized_text": tokens,
        # "cold" @0 and "headache" @2 — inclusive single-token spans.
        "ner": [[0, 0, "SYMPTOM"], [2, 2, "SYMPTOM"]],
        "ner_char": [[0, 4, "SYMPTOM"], [9, 17, "SYMPTOM"]],
    }

    out = _window_example(item, max_tokens=256, pad=64)

    # Both spans co-occur -> exactly one windowed example carrying both.
    assert len(out) == 1
    win = out[0]
    assert len(win["ner"]) == 2
    assert len(win["tokenized_text"]) <= 256

    # Realignment: token spans still slice to the same surface tokens, char spans
    # slice the windowed text back to the same strings.
    surfaces = {"cold", "headache"}
    got = set()
    for (start, end, _), (c_start, c_end, _) in zip(win["ner"], win["ner_char"]):
        token_surface = " ".join(win["tokenized_text"][start : end + 1])
        assert win["text"][c_start:c_end] == token_surface
        got.add(token_surface)
    assert got == surfaces


def test_window_splits_far_apart_spans():
    """Spans too far apart to share a window spill into separate windows."""
    tokens = ["start"] + ["x"] * 400 + ["end"]
    # "start" @0 and "end" @401 are >max_tokens apart -> cannot co-occur.
    item = {
        "text": " ".join(tokens),
        "tokenized_text": tokens,
        "ner": [[0, 0, "L"], [401, 401, "L"]],
        "ner_char": [
            [0, 5, "L"],
            [len(" ".join(tokens)) - 3, len(" ".join(tokens)), "L"],
        ],
    }

    out = _window_example(item, max_tokens=256, pad=64)

    assert len(out) == 2
    for win in out:
        assert len(win["tokenized_text"]) <= 256
        assert len(win["ner"]) == 1
        start, end, _ = win["ner"][0]
        c_start, c_end, _ = win["ner_char"][0]
        assert win["text"][c_start:c_end] == " ".join(
            win["tokenized_text"][start : end + 1]
        )


def test_window_enforces_hard_cap():
    """No emitted window exceeds max_tokens even with a tight budget."""
    tokens = ["w"] * 50
    item = {
        "text": " ".join(tokens),
        "tokenized_text": tokens,
        "ner": [[0, 0, "L"], [49, 49, "L"]],
        "ner_char": [
            [0, 1, "L"],
            [len(" ".join(tokens)) - 1, len(" ".join(tokens)), "L"],
        ],
    }

    out = _window_example(item, max_tokens=16, pad=4)

    assert out, "expected at least one window"
    for win in out:
        assert len(win["tokenized_text"]) <= 16
