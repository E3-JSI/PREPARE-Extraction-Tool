import json
import logging
import math
import os
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import torch
from gliner import GLiNER
from gliner.data_processing.collator import SpanDataCollator
from gliner.training import Trainer, TrainingArguments
from torch.utils.data import Dataset as TorchDataset
from transformers import TrainerCallback

from app.core.settings import settings
from app.interfaces import Entity
from app.library.ner_metrics import NERMetrics
from app.training.memory_budget import (
    check_memory_budget,
    ensure_memory_headroom,
    release_freed_memory,
)

logger = logging.getLogger(__name__)


class _TrainingStopped(Exception):
    """Raised internally when a cooperative stop checkpoint sees the stop event.

    Used to unwind long-running loops (e.g. the eval loop) promptly so the worker
    can end the run as ``stopped`` rather than running to completion.
    """


# -----------------------------
# Backend callback config
# -----------------------------

BACKEND_HOST = settings.BACKEND_HOST
CALLBACK_URL = f"{BACKEND_HOST}/api/v1/bioner/internal/training-events"


# Error-analysis caps keep the payload bounded: up to this many example errors of
# each kind (false positive / false negative) per label, and each example's
# context text is truncated to this many characters around the offending span.
MAX_ERROR_EXAMPLES_PER_KIND = 5
MAX_ERROR_TEXT_CHARS = 300


def _error_snippet(text: str, start: int, end: int) -> tuple[str, int, int]:
    """Return a bounded context snippet around ``[start, end]`` with adjusted offsets.

    Short texts are returned unchanged. Longer ones are cropped to a window of
    ``MAX_ERROR_TEXT_CHARS`` centred on the span, with ellipses marking removed
    text; the returned offsets point at the span inside the snippet.

    Args:
        text (str): The full sentence text.
        start (int): Span start offset in ``text``.
        end (int): Span end offset in ``text``.

    Returns:
        tuple[str, int, int]: ``(snippet, start_in_snippet, end_in_snippet)``.
    """
    if len(text) <= MAX_ERROR_TEXT_CHARS:
        return text, start, end

    span_len = max(0, end - start)
    pad = max(0, (MAX_ERROR_TEXT_CHARS - span_len) // 2)
    win_start = max(0, start - pad)
    win_end = min(len(text), win_start + MAX_ERROR_TEXT_CHARS)
    win_start = max(0, win_end - MAX_ERROR_TEXT_CHARS)

    prefix = "…" if win_start > 0 else ""
    suffix = "…" if win_end < len(text) else ""
    snippet = prefix + text[win_start:win_end] + suffix
    offset = len(prefix) - win_start
    return snippet, start + offset, end + offset


def _error_example(
    text: str, gold: Optional[Entity], predicted: Optional[Entity]
) -> dict:
    """Build a single bounded error example with a snippet centred on the span.

    Exactly one of ``gold`` / ``predicted`` is set: a missed gold span (false
    negative) or a wrongly predicted span (false positive). Offsets in the
    returned span are relative to the (possibly truncated) ``text``.
    """
    span = gold or predicted
    snippet, s, e = _error_snippet(text, span.start, span.end)

    def _span(ent: Optional[Entity], new_start: int, new_end: int) -> Optional[dict]:
        if ent is None:
            return None
        return {
            "text": ent.text,
            "start": new_start,
            "end": new_end,
            "label": ent.label,
        }

    return {
        "text": snippet,
        "gold": _span(gold, s, e),
        "predicted": _span(predicted, s, e),
    }


def gliner_to_entities(text: str, preds: list[dict]) -> list[Entity]:
    return [
        Entity(
            text=text[p["start"] : p["end"]],
            start=p["start"],
            end=p["end"],
            label=p["label"],
        )
        for p in preds
    ]


def gold_to_entities(text: str, gold: list[list]) -> list[Entity]:
    return [
        Entity(
            text=text[start:end],
            start=start,
            end=end,
            label=label,
        )
        for start, end, label in gold
    ]


def _token_char_starts(tokens: list[str]) -> list[int]:
    """Char start offset of each token in ``" ".join(tokens)``.

    Tokens are joined by single spaces, so every token starts one character past
    the end of the previous one. Shared by span cleaning and window realignment
    so both derive character offsets from the exact same join logic.

    Args:
        tokens (list[str]): The token strings.

    Returns:
        list[int]: The character start offset of each token.
    """
    starts: list[int] = []
    offset = 0
    for tok in tokens:
        starts.append(offset)
        offset += len(tok) + 1
    return starts


def _window_example(item: dict, max_tokens: int, pad: int) -> list[dict]:
    """Split a cleaned token-form item into bounded, span-centred windows.

    Long records blow up GLiNER's ``seq_len x span_width x num_classes`` score
    tensor and make the first CPU step crawl. This trims each example to windows
    of at most ``max_tokens`` tokens centred on its span groups: co-occurring
    spans that fit within the budget are greedily packed into ONE window (so a
    record like "the patient has a cold and a headache" stays a single two-span
    example), and only spans too far apart to share a window spill into additional
    windows.

    Works in token space on the corrected inclusive spans, then recomputes both
    the token ``ner`` (offset by the window start) and the character ``ner_char``
    (from the windowed tokens via :func:`_token_char_starts`) so realignment is
    exact.

    Args:
        item (dict): A cleaned item with ``tokenized_text``, inclusive token
            spans in ``ner`` and character spans in ``ner_char``.
        max_tokens (int): Hard cap on tokens per window; no emitted window ever
            exceeds this.
        pad (int): Context tokens kept on each side of a span group.

    Returns:
        list[dict]: One or more windowed items with realigned spans. Returns the
            input unchanged (single-item list) when it already fits within
            ``max_tokens``. A span wider than ``max_tokens`` on its own is dropped
            (logged) rather than shipped oversized.
    """
    tokens = item["tokenized_text"]
    ner = item["ner"]

    if len(tokens) <= max_tokens or not ner:
        return [item]

    last_idx = len(tokens) - 1

    # Greedily pack spans (in start order) into groups whose padded extent fits
    # the budget. A span only opens a new group when it cannot share the current
    # one — never one-window-per-span while they could co-occur.
    spans = sorted(ner, key=lambda s: (s[0], s[1]))
    groups: list[list[list]] = []
    current: list[list] = []
    cur_min = cur_max = 0
    for span in spans:
        start, end, _ = span
        if not current:
            current = [span]
            cur_min, cur_max = start, end
            continue
        new_min = min(cur_min, start)
        new_max = max(cur_max, end)
        win_start = max(0, new_min - pad)
        win_end = min(last_idx, new_max + pad)
        if win_end - win_start + 1 <= max_tokens:
            current.append(span)
            cur_min, cur_max = new_min, new_max
        else:
            groups.append(current)
            current = [span]
            cur_min, cur_max = start, end
    if current:
        groups.append(current)

    windows: list[dict] = []
    for group in groups:
        g_min = min(s[0] for s in group)
        g_max = max(s[1] for s in group)
        win_start = max(0, g_min - pad)
        win_end = min(last_idx, g_max + pad)
        # Hard cap: only reachable when a single span's own extent exceeds the
        # budget; clamp the window and drop spans that fall outside it below.
        if win_end - win_start + 1 > max_tokens:
            win_end = min(last_idx, win_start + max_tokens - 1)

        win_tokens = tokens[win_start : win_end + 1]
        char_starts = _token_char_starts(win_tokens)

        win_ner: list[list] = []
        win_ner_char: list[list] = []
        for start, end, label in group:
            if start < win_start or end > win_end:
                logger.warning(
                    "Dropping span [%d, %d] (%s): wider than max_tokens=%d",
                    start,
                    end,
                    label,
                    max_tokens,
                )
                continue
            rel_start = start - win_start
            rel_end = end - win_start
            win_ner.append([rel_start, rel_end, label])
            char_start = char_starts[rel_start]
            char_end = char_starts[rel_end] + len(win_tokens[rel_end])
            win_ner_char.append([char_start, char_end, label])

        if win_ner:
            windows.append(
                {
                    "text": " ".join(win_tokens),
                    "tokenized_text": win_tokens,
                    "ner": win_ner,
                    "ner_char": win_ner_char,
                }
            )

    return windows


class GLiNERDataset(TorchDataset):
    """Minimal torch Dataset over GLiNER-format samples.

    Yields ``text``/``ner``/``tokenized_text`` per item, falling back to a
    whitespace split when ``tokenized_text`` is absent. Note this strips other
    keys (e.g. ``ner_char``), so evaluation reads gold spans from the raw items
    instead of from this dataset.
    """

    def __init__(self, data):
        self.data = data

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        item = self.data[idx]

        # If tokenized_text exists, use it; otherwise just use plain text
        tokenized_text = item.get("tokenized_text")
        if not tokenized_text:
            # Fallback: tokenize the text if not provided
            tokenized_text = item["text"].split()

        return {
            "text": item["text"],
            "ner": item["ner"],
            "tokenized_text": tokenized_text,
        }


def _per_positive_mean_loss(summed_loss, num_positives):
    """Normalize a sum-reduced GLiNER loss per positive span for reporting.

    GLiNER's ``Trainer`` backprops the loss summed over every score element.
    A per-element mean is useless with focal loss: >99.9% of elements are easy
    negatives whose contribution focal loss shrinks toward zero, flattening the
    curve to ~1e-3. Dividing by the positive-span count instead (the standard
    focal-loss normalizer, cf. RetinaNet) keeps the curve in a familiar range
    without touching the gradient signal.

    Accepts a tensor or a plain float and returns the same kind. Batches with
    no positive spans divide by 1.
    """
    return summed_loss / max(num_positives, 1)


# -----------------------------
# Trainer
# -----------------------------
class GLiNERFinetuner:
    """Runs one fine-tuning job and reports via backend events only."""

    def __init__(
        self,
        run_id: int,
        base_model_path: str,
        training_data: list[dict],
        eval_data: Optional[list[dict]] = None,
        device: str = "cpu",
        num_epochs: int = 4,
        learning_rate: float = 5e-6,
        train_batch_size: int = 8,
        val_ratio: float = 0.2,
    ):
        self.run_id = run_id
        self.base_model_path = base_model_path
        self.training_data = training_data
        self.eval_data = eval_data or []

        self.device = device
        self.num_epochs = num_epochs
        self.learning_rate = learning_rate
        self.train_batch_size = train_batch_size
        self.val_ratio = val_ratio

        self._status = "idle"
        self._status_lock = threading.Lock()
        self._stop_event = threading.Event()

        self._events: list[dict] = []
        self._events_lock = threading.Lock()

        self._output_path: Optional[str] = None
        self._error: Optional[str] = None

    # -----------------------------
    # STOP
    # -----------------------------
    def request_stop(self) -> None:
        self._stop_event.set()

    def _emit_stopped(self) -> None:
        """Mark the run terminal-stopped and notify the UI.

        Used by every cooperative-stop unwind path so a stop always both frees
        the job slot (terminal status) and emits a ``stopped`` event.
        """
        self._set_status("stopped")
        self._emit({"type": "stopped", "run_id": self.run_id})

    # -----------------------------
    # STEP MATH HELPERS
    # -----------------------------
    def _compute_total_steps(self, train_size: int) -> int:
        """Total optimizer steps, mirroring HF Trainer's accumulation math."""
        micro_batch, accum_steps = self._compute_micro_batch()
        micro_batches_per_epoch = max(1, math.ceil(train_size / micro_batch))
        steps_per_epoch = max(1, micro_batches_per_epoch // accum_steps)
        return max(1, steps_per_epoch * self.num_epochs)

    def _compute_eval_steps(self, total_steps: int) -> int:
        """Eval interval in optimizer steps (>=1)."""
        explicit = settings.BIONER_TRAIN_EVAL_STEPS
        if explicit >= 1:
            return explicit
        TARGET_POINTS = 18
        return max(1, total_steps // TARGET_POINTS)

    def _compute_micro_batch(self) -> tuple[int, int]:
        """Micro-batch size and accumulation steps for the effective batch."""
        cap = max(1, settings.BIONER_TRAIN_MICRO_BATCH)
        batch = max(1, self.train_batch_size)
        micro = next(m for m in range(min(cap, batch), 0, -1) if batch % m == 0)
        return micro, batch // micro

    # -----------------------------
    # STATUS (thread-safe)
    # -----------------------------
    def _set_status(self, status: str) -> None:
        with self._status_lock:
            self._status = status

    def _get_status(self) -> str:
        with self._status_lock:
            return self._status

    # -----------------------------
    # SNAPSHOT
    # -----------------------------
    def get_snapshot(self) -> dict:
        with self._events_lock:
            events = list(self._events)

        return {
            "status": self._get_status(),
            "new_events": events,
            "output_path": self._output_path,
            "error": self._error,
        }

    # -----------------------------
    # EVENT EMITTER
    # -----------------------------
    def _emit(self, event: dict):
        # DEBUG LOG
        logger.info(
            f"[TRAIN EVENT] run={event.get('run_id')} "
            f"type={event.get('type')} "
            f"payload={event}"
        )

        with self._events_lock:
            self._events.append(event)

        def _send():
            try:
                response = requests.post(CALLBACK_URL, json=event, timeout=3)

                logger.info(
                    f"[CALLBACK SENT] "
                    f"status={response.status_code} "
                    f"type={event.get('type')}"
                )

            except Exception as e:
                logger.exception(
                    f"[CALLBACK FAILED] type={event.get('type')} error={e}"
                )

        threading.Thread(target=_send, daemon=True).start()

    # -----------------------------
    # RUN ENTRY
    # -----------------------------
    def run(self) -> None:
        self._set_status("running")

        try:
            self._do_train()
        except Exception as e:
            logger.error(f"Training run {self.run_id} failed: {e}", exc_info=True)
            self._set_status("failed")
            self._error = str(e)

            self._emit(
                {
                    "type": "error",
                    "run_id": self.run_id,
                    "message": str(e),
                }
            )

        finally:
            # A stopped run must actually release its memory, or the leftovers
            # count against the next run's budget.
            self.training_data = []
            self.eval_data = []
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            release_freed_memory()

    # -----------------------------
    # TRAINING CORE
    # -----------------------------

    def _clean_items(self, data: list[dict]) -> list[dict]:
        """Normalize raw items into GLiNER trainer format.

        Accepts the backend token form ``{"tokenized_text": [...], "ner":
        [[tok_start, tok_end, label], ...]}`` or the legacy char form
        ``{"text": ..., "entities": [...]}``. Token-form items keep their
        ``tokenized_text`` plus character spans in ``ner_char`` (used by eval and
        serialized samples, which slice ``text[start:end]``); ``ner`` stays as
        token spans for the GLiNER collator. Items that yield no valid spans are
        dropped.

        Args:
            data (list[dict]): Raw training or evaluation items.

        Returns:
            list[dict]: Cleaned items ready for training/evaluation.
        """
        cleaned_data: list[dict] = []

        for item in data:
            # Check if data is already in GLiNER token format from backend
            if "tokenized_text" in item and "ner" in item:
                tokenized_text = item.get("tokenized_text", [])
                ner = item.get("ner", [])

                if not isinstance(tokenized_text, list) or not tokenized_text:
                    continue

                if not isinstance(ner, list):
                    continue

                # Reconstruct text by joining tokens with spaces
                tokens = [str(t) for t in tokenized_text]
                text = " ".join(tokens)

                if not text.strip():
                    continue

                # Char start offset of each token in the joined `text`
                # (tokens are joined by single spaces).
                token_char_starts = _token_char_starts(tokens)

                # Validate NER entries (token indices should be in range).
                # `ner` stays as INCLUSIVE TOKEN spans into `tokenized_text` —
                # that is what GLiNER's collator consumes. GLiNER 0.2.x builds
                # candidate spans as ``(start, start + width)`` with ``width``
                # starting at 0, so a single-token entity at token ``i`` is the
                # inclusive span ``(i, i)`` and the gold lookup is an exact tuple
                # match. Keeping the end token as-is (no ``+ 1``) is what makes the
                # target line up; a ``+ 1`` trains the model one token too wide and
                # silently drops any entity ending on the last token. Everything
                # that slices ``text[start:end]`` (eval, serialized samples) must
                # use the CHARACTER spans kept in `ner_char` instead.
                valid_ner = []
                valid_ner_char = []
                for ent in ner:
                    if isinstance(ent, (list, tuple)) and len(ent) == 3:
                        start_tok, end_tok, label = ent
                        if (
                            isinstance(start_tok, int)
                            and isinstance(end_tok, int)
                            and isinstance(label, str)
                        ):
                            # Token indices are already correct, just validate bounds
                            if 0 <= start_tok <= end_tok < len(tokenized_text):
                                valid_ner.append([start_tok, end_tok, label])
                                char_start = token_char_starts[start_tok]
                                char_end = token_char_starts[end_tok] + len(
                                    tokens[end_tok]
                                )
                                valid_ner_char.append([char_start, char_end, label])

                if valid_ner:
                    cleaned_item = {
                        "text": text,
                        "tokenized_text": tokens,
                        "ner": valid_ner,
                        "ner_char": valid_ner_char,
                    }
                    # TODO(structural-chunking): tier-1 sentence/section split
                    # (syntok/medspacy) before the span-window fallback —
                    # rule-based segmenters are weak on messy bulleted clinical
                    # text, so span-window is the robust default we ship first.
                    cleaned_data.extend(
                        _window_example(
                            cleaned_item,
                            settings.BIONER_TRAIN_MAX_TOKENS,
                            settings.BIONER_TRAIN_CONTEXT_PAD,
                        )
                    )
                continue

            # FALLBACK: Old format with "entities" field (character-based)
            text = item.get("text")
            entities = item.get("entities", [])

            if not isinstance(text, str) or not text.strip():
                continue

            if not isinstance(entities, list):
                continue

            ner = []

            for ent in entities:
                if not isinstance(ent, (list, tuple, dict)):
                    continue

                if isinstance(ent, (list, tuple)) and len(ent) == 3:
                    start, end, label = ent
                elif isinstance(ent, dict):
                    start = ent.get("start")
                    end = ent.get("end")
                    label = ent.get("label")
                else:
                    continue

                if not isinstance(start, int) or not isinstance(end, int):
                    continue

                if not isinstance(label, str):
                    continue

                if start < 0 or end > len(text) or start >= end:
                    continue

                span = text[start:end]
                if len(span.strip()) == 0:
                    continue

                ner.append([start, end, label])

            if ner:
                cleaned_data.append({"text": text, "ner": ner})

        return cleaned_data

    def evaluate_model(self, model, dataset, labels):
        """Evaluate the model and compute per-label exact and relaxed F1.

        Args:
            model: A GLiNER model exposing ``predict_entities``.
            dataset: An iterable of items with ``text`` and ``ner`` keys.
            labels (list[str]): Labels to evaluate.

        Returns:
            tuple: A ``(metrics, evaluation_samples)`` pair where ``metrics``
                contains a ``per_label`` mapping of label -> dict with
                ``exact_f1``, ``relaxed_f1``, ``precision``, ``recall`` plus
                relaxed false-positive/false-negative counts (``fp``, ``fn``) and
                a bounded list of ``examples`` (concrete error records, each with
                ``text`` and a ``gold``/``predicted`` span).
        """
        true_entities = []
        pred_entities = []

        evaluation_samples = []

        for item in dataset:
            # Cooperative stop checkpoint: this loop runs predict_entities over
            # every eval item and can take minutes on CPU. Bail within one item
            # of a stop request so the run can wind down promptly. Shared by both
            # baseline and final evaluation.
            if self._stop_event.is_set():
                raise _TrainingStopped()

            text = item["text"]

            predictions = model.predict_entities(
                text,
                labels,
                threshold=0.5,
            )

            # Token-form items carry CHARACTER spans in ``ner_char``; char-form
            # items only have ``ner`` (already character offsets). gold spans are
            # sliced as ``text[start:end]`` so they must be character offsets.
            gold = gold_to_entities(text, item.get("ner_char", item["ner"]))
            pred = [
                Entity(
                    text=p["text"],
                    start=p["start"],
                    end=p["end"],
                    label=p["label"],
                )
                for p in predictions
            ]

            true_entities.append(gold)
            pred_entities.append(pred)

            evaluation_samples.append(
                {
                    "text": text,
                    "gold": [
                        {
                            "text": e.text,
                            "start": e.start,
                            "end": e.end,
                            "label": e.label,
                        }
                        for e in gold
                    ],
                    "predicted": [
                        {
                            "text": e.text,
                            "start": e.start,
                            "end": e.end,
                            "label": e.label,
                        }
                        for e in pred
                    ],
                }
            )

        metric_engine = NERMetrics(metrics=["exact", "relaxed"])

        # Per-label exact + relaxed F1 (plus relaxed precision/recall).
        per_label: dict[str, dict[str, float]] = {}
        for label in labels:
            _, _, exact_f1 = metric_engine.evaluate_ner_performance(
                true_entities,
                pred_entities,
                match_type="exact",
                label=label,
            )
            precision, recall, relaxed_f1 = metric_engine.evaluate_ner_performance(
                true_entities,
                pred_entities,
                match_type="relaxed",
                label=label,
            )

            # Per-label error analysis: relaxed FP/FN counts plus a bounded sample
            # of concrete example errors (missed gold spans / wrong predictions).
            fp_count = 0
            fn_count = 0
            fp_examples: list[dict] = []
            fn_examples: list[dict] = []
            for sample, gold_ents, pred_ents in zip(
                evaluation_samples, true_entities, pred_entities
            ):
                false_positives, false_negatives = metric_engine.sentence_errors(
                    gold_ents, pred_ents, match_type="relaxed", label=label
                )
                fp_count += len(false_positives)
                fn_count += len(false_negatives)
                for ent in false_negatives:
                    if len(fn_examples) < MAX_ERROR_EXAMPLES_PER_KIND:
                        fn_examples.append(
                            _error_example(sample["text"], gold=ent, predicted=None)
                        )
                for ent in false_positives:
                    if len(fp_examples) < MAX_ERROR_EXAMPLES_PER_KIND:
                        fp_examples.append(
                            _error_example(sample["text"], gold=None, predicted=ent)
                        )

            per_label[label] = {
                "exact_f1": round(exact_f1, 4),
                "relaxed_f1": round(relaxed_f1, 4),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "fp": fp_count,
                "fn": fn_count,
                "examples": fn_examples + fp_examples,
            }

        # Micro-averaged (over all labels) relaxed scores for convenience.
        precision, recall, relaxed_f1 = metric_engine.evaluate_ner_performance(
            true_entities,
            pred_entities,
            match_type="relaxed",
        )
        _, _, exact_f1 = metric_engine.evaluate_ner_performance(
            true_entities,
            pred_entities,
            match_type="exact",
        )

        metrics = {
            "exact_f1": round(exact_f1, 4),
            "relaxed_f1": round(relaxed_f1, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "per_label": per_label,
        }

        return metrics, evaluation_samples

    def _do_train(self) -> None:
        if not self.training_data:
            raise ValueError("No training examples provided")

        self._emit(
            {
                "type": "training_info",
                "run_id": self.run_id,
                "train_size": len(self.training_data),
            }
        )

        print("\n" + "=" * 80)
        print(f"[GLINER TRAINER] RUN ID: {self.run_id}")
        print(f"[GLINER TRAINER] USING MODEL: {self.base_model_path}")
        print(f"[GLINER TRAINER] DEVICE: {self.device}")
        print("=" * 80 + "\n")

        # Refuse models that can't fit before loading anything.
        check_memory_budget(self.base_model_path)

        model = GLiNER.from_pretrained(
            self.base_model_path,
            local_files_only=False,
        ).to(self.device)

        if self._stop_event.is_set():
            self._emit_stopped()
            return

        cleaned_data, cleaned_eval = self._prepare_cleaned_data()

        self._dump_cleaned_data(cleaned_data)

        train_data, val_data, total, train_pct, val_pct = self._split_data(
            cleaned_data, cleaned_eval
        )

        train_ds, eval_ds, collator, args, labels, total_steps = (
            self._build_training_components(model, cleaned_data, train_data, val_data)
        )

        trainer = self._build_trainer(model, args, train_ds, eval_ds, collator)

        print("CALLBACKS:", trainer.callback_handler.callbacks)

        self._emit(
            {
                "type": "training_start",
                "run_id": self.run_id,
                "num_epochs": self.num_epochs,
                "total_steps": total_steps,
            }
        )

        for i, ex in enumerate(train_ds):
            if ex.get("text") is None:
                raise ValueError(f"Broken sample at {i}: text=None")

        # Baseline: evaluate the untrained base model on the same eval split, so the
        # comparison dashboard has a same-split reference point for the default
        # extraction model (the run's starting weights). Best-effort — it runs
        # inside this background training job and never blocks anything else.
        if not self._stop_event.is_set():
            try:
                self._run_baseline_evaluation(model, val_data, labels)
            except _TrainingStopped:
                self._emit_stopped()
                return

        try:
            trainer.train()

            self._run_evaluation(
                model, val_data, labels, train_data, total, train_pct, val_pct
            )

        except (KeyboardInterrupt, _TrainingStopped):
            self._emit_stopped()
            return

        if self._stop_event.is_set():
            self._emit_stopped()
            return

        self._save_model(model)

    def _prepare_cleaned_data(self) -> tuple[list[dict], list[dict]]:
        """Normalize raw training (and optional eval) items into GLiNER samples.

        Returns:
            tuple[list[dict], list[dict]]: ``(cleaned_data, cleaned_eval)``.

        Raises:
            ValueError: If no valid training samples remain after conversion.
        """
        print("\nTRAINING DATA PREVIEW:")
        for i, item in enumerate(self.training_data[:3]):
            print(f"\nSample {i}:")
            print("text:", item.get("text"))
            print("labels:", item.get("labels"))
            print("ner:", item.get("ner"))

        # Normalize raw training (and optional eval) items into trainer format.
        cleaned_data = self._clean_items(self.training_data)

        if not cleaned_data:
            raise ValueError(
                "No valid training samples after conversion. "
                "Check if labels exist inside text."
            )

        # Separate eval datasets (if provided) are cleaned the same way and used
        # in place of a held-out split below.
        cleaned_eval = self._clean_items(self.eval_data)

        print("\nCONVERTED GLiNER DATA:")
        for i, item in enumerate(cleaned_data[:3]):
            print(f"\nSample {i}:")
            print(item)

        return cleaned_data, cleaned_eval

    def _dump_cleaned_data(self, cleaned_data: list[dict]) -> None:
        """Persist ``cleaned_data`` to JSON for inspection/debugging."""
        # Save cleaned_data to JSON for inspection/debugging
        BASE_DIR = Path.cwd()
        data_output_dir = BASE_DIR / "training_data"
        data_output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cleaned_data_file = (
            data_output_dir / f"cleaned_training_data_run{self.run_id}_{timestamp}.json"
        )

        with open(cleaned_data_file, "w", encoding="utf-8") as f:
            json.dump(cleaned_data, f, indent=2, ensure_ascii=False)

        abs_path = cleaned_data_file.resolve()
        print("\nSAVED cleaned training data")
        print(f"   Filename: {cleaned_data_file.name}")
        print(f"   Full path: {abs_path}")
        print(f"   Total samples: {len(cleaned_data)}")

    def _split_data(
        self, cleaned_data: list[dict], cleaned_eval: list[dict]
    ) -> tuple[list[dict], list[dict], int, float, float]:
        """Seeded shuffle + train/val split (or separate eval set), with logging.

        Returns:
            tuple: ``(train_data, val_data, total, train_pct, val_pct)``.
        """
        random.seed(42)
        random.shuffle(cleaned_data)

        total = len(cleaned_data)

        if cleaned_eval:
            # Separate eval datasets: train on all of cleaned_data, evaluate on
            # the provided eval set (no held-out split).
            train_data = cleaned_data
            val_data = cleaned_eval
        elif self.val_ratio > 0:
            split_idx = int(len(cleaned_data) * (1 - self.val_ratio))
            train_data = cleaned_data[:split_idx]
            val_data = cleaned_data[split_idx:]
        else:
            train_data = cleaned_data
            val_data = []

        # ----------------------------
        # LOG SPLIT STATS
        # ----------------------------

        train_pct = (len(train_data) / total) * 100 if total else 0
        val_pct = (len(val_data) / total) * 100 if total else 0

        print("\nDATA SPLIT SUMMARY")
        print(f"Total samples      : {total}")
        print(f"Train samples      : {len(train_data)} ({train_pct:.1f}%)")
        print(f"Validation samples : {len(val_data)} ({val_pct:.1f}%)")

        return train_data, val_data, total, train_pct, val_pct

    def _build_training_components(
        self,
        model,
        cleaned_data: list[dict],
        train_data: list[dict],
        val_data: list[dict],
    ) -> tuple[
        GLiNERDataset,
        "GLiNERDataset | None",
        SpanDataCollator,
        TrainingArguments,
        list[str],
        int,
    ]:
        """Build the train dataset, eval dataset, collator, training args, eval labels, and total steps.

        Also runs lightweight sample/span sanity checks before training.

        Returns:
            tuple: ``(train_ds, eval_ds, collator, args, labels, total_steps)``.
        """
        train_ds = GLiNERDataset(train_data)
        eval_ds = GLiNERDataset(val_data) if val_data else None
        # Eval reads gold spans from the raw items (which carry `ner_char`);
        # GLiNERDataset.__getitem__ would strip that key, so pass `val_data`.

        collator = SpanDataCollator(
            model.config,
            data_processor=model.data_processor,
            prepare_labels=True,
        )

        for i, ex in enumerate(cleaned_data[:5]):
            assert ex.get("text") is not None, f"Missing text at {i}"
            assert ex.get("ner") is not None, f"Missing ner at {i}"

        BASE_DIR = Path.cwd()
        OUTPUT_ROOT = BASE_DIR / "models" / "gliner"

        base_name = Path(self.base_model_path).name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        output_dir = OUTPUT_ROOT / f"{base_name}-finetuned-{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nSAVING MODEL TRAINING FILE TO: {output_dir}\n")
        print("Current working dir:", os.getcwd())

        total_steps = self._compute_total_steps(len(train_data))
        eval_steps = self._compute_eval_steps(total_steps)
        micro_batch, accum_steps = self._compute_micro_batch()

        eval_kwargs: dict = {}
        if eval_ds is not None:
            eval_kwargs = dict(
                eval_strategy="steps",
                eval_steps=eval_steps,
                # Full batch here (unlike training): eval is a no-grad forward
                # pass, so it has none of the activation memory that made the
                # training batch OOM — and a bigger batch keeps the per-step
                # eval-loss pass fast.
                per_device_eval_batch_size=self.train_batch_size,
            )

        args = TrainingArguments(
            output_dir=output_dir,
            num_train_epochs=self.num_epochs,
            learning_rate=self.learning_rate,
            focal_loss_alpha=0.75,
            focal_loss_gamma=2,
            others_lr=1e-5,
            weight_decay=0.01,
            others_weight_decay=0.01,
            lr_scheduler_type="linear",
            warmup_ratio=0.1,
            save_strategy="no",
            fp16=False,
            use_cpu=(self.device == "cpu"),
            dataloader_num_workers=0,
            per_device_train_batch_size=micro_batch,
            gradient_accumulation_steps=accum_steps,
            report_to="none",
            logging_strategy="steps",
            # Log every step so the live loss curve populates promptly and densely
            # rather than only every 10th step (which on small datasets meant the
            # curve appeared late / barely at all).
            logging_steps=1,
            **eval_kwargs,
        )

        print("\nCHECK SAMPLE SPANS:")
        for i, item in enumerate(cleaned_data[:3]):
            text = item["text"]
            tokenized_text = item.get("tokenized_text", [])

            # If we have tokenized_text, spans are token indices; otherwise character indices
            if tokenized_text:
                # Token spans are INCLUSIVE, so end indexes a real token
                # (end < len) and a single-token entity has start == end.
                for start, end, label in item["ner"]:
                    assert 0 <= start <= end < len(tokenized_text), (
                        f"Token index out of bounds: [{start}:{end}] for {len(tokenized_text)} tokens"
                    )
            else:
                # Character indices - validate span is not empty
                for start, end, label in item["ner"]:
                    assert text[start:end], "Empty span detected"
                    assert start < end

        # Derive eval labels from the train+val union so labels that appear only
        # in the validation/eval split are still scored.
        labels = list(
            set(e[2] for item in [*train_data, *val_data] for e in item["ner"])
        )
        print("labels:", labels)

        return train_ds, eval_ds, collator, args, labels, total_steps

    def _build_trainer(self, model, args, train_ds, eval_ds, collator):
        """Build the tracking GLiNER trainer wired to this finetuner's events."""
        finetuner = self

        class ProgressCallback(TrainerCallback):
            def on_epoch_end(self, args, state, control, **kwargs):
                finetuner._emit(
                    {
                        "type": "epoch_update",
                        "run_id": finetuner.run_id,
                        "epoch": float(state.epoch or 0),
                    }
                )

            def on_log(self, args, state, control, logs=None, **kwargs):
                if not logs:
                    return

                # Emit an epoch-progress tick for the live UI only. Loss is NOT
                # attached here: `_TrackingTrainer.log` already streams it as a
                # `train_log` (the authoritative per-step metric), so attaching it
                # would double-count loss points on the curve.
                finetuner._emit(
                    {
                        "type": "epoch_update",
                        "run_id": finetuner.run_id,
                        "epoch": float(state.epoch or 0),
                    }
                )

        class _TrackingTrainer(Trainer):
            # Positive-span count of the most recent batch, captured in
            # compute_loss so the *reported* loss can be normalized per
            # positive span without changing backprop.
            _last_positive_count: int = 0

            def training_step(self, model, inputs, num_items_in_batch=None):
                if finetuner._stop_event.is_set():
                    self.control.should_training_stop = True
                    raise KeyboardInterrupt("Training stopped by user")
                ensure_memory_headroom()
                # super() backpropagates the sum-reduced loss (gradient signal
                # unchanged); only the returned/logged value is normalized.
                loss = super().training_step(model, inputs)
                return _per_positive_mean_loss(loss, self._last_positive_count)

            def compute_loss(self, model, inputs, *args, **kwargs):
                if finetuner._stop_event.is_set():
                    self.control.should_training_stop = True
                    raise KeyboardInterrupt("Stopped before loss computation")
                # Mirror gliner's Trainer.compute_loss forward exactly so the
                # returned (summed) loss — and thus backprop — is unchanged.
                outputs = model(
                    alpha=self.args.focal_loss_alpha,
                    gamma=self.args.focal_loss_gamma,
                    prob_margin=self.args.focal_loss_prob_margin,
                    label_smoothing=self.args.label_smoothing,
                    reduction=self.args.loss_reduction,
                    negatives=self.args.negatives,
                    masking=self.args.masking,
                    **inputs,
                )
                labels = inputs.get("labels")
                self._last_positive_count = (
                    int((labels > 0).sum().item()) if labels is not None else 0
                )
                return outputs.loss

            def prediction_step(
                self, model, inputs, prediction_loss_only, ignore_keys=None
            ):
                # Compute the eval loss with the same (focal) loss args as
                # training — the model's bare forward defaults to plain BCE —
                # and normalize it to the same per-positive scale, so the two
                # curves share one objective and scale.
                with torch.no_grad():
                    with self.compute_loss_context_manager():
                        outputs = model(
                            alpha=self.args.focal_loss_alpha,
                            gamma=self.args.focal_loss_gamma,
                            prob_margin=self.args.focal_loss_prob_margin,
                            label_smoothing=self.args.label_smoothing,
                            reduction=self.args.loss_reduction,
                            negatives=self.args.negatives,
                            masking=self.args.masking,
                            **inputs,
                        )
                    loss = outputs.loss
                    logits = outputs.logits
                    labels = inputs["labels"]
                if loss is not None and labels is not None:
                    loss = _per_positive_mean_loss(loss, int((labels > 0).sum().item()))
                if prediction_loss_only:
                    return (loss, None, None)
                return (loss, logits, labels)

            def log(self, logs: dict, *args: Any, **kwargs: Any) -> None:
                super().log(logs, *args, **kwargs)

                if finetuner._stop_event.is_set():
                    self.control.should_training_stop = True

                event = {
                    "type": "train_log",
                    "run_id": finetuner.run_id,
                    "step": getattr(self.state, "global_step", None),
                    "epoch": float(getattr(self.state, "epoch", 0) or 0),
                }

                # forward ALL useful metrics safely
                metric_keys = ["loss", "grad_norm", "learning_rate", "eval_loss"]
                for key in metric_keys:
                    if key in logs and logs[key] is not None:
                        event[key] = float(logs[key])

                # Only emit when at least one real metric is present. The base event
                # already carries 4 keys, so a length check is always true — guard on
                # the metric keys instead so summary/empty logs don't stream a point.
                if any(key in event for key in metric_keys):
                    finetuner._emit(event)

        trainer = _TrackingTrainer(
            model=model,
            args=args,
            train_dataset=train_ds,
            eval_dataset=eval_ds,
            data_collator=collator,
            callbacks=[ProgressCallback()],
        )

        return trainer

    def _run_baseline_evaluation(
        self, model, val_data: list[dict], labels: list[str]
    ) -> None:
        """Evaluate the untrained base model and emit a baseline result.

        Gives the comparison dashboard a same-split reference point for the
        default extraction model (the run's starting weights). Best-effort: any
        failure is logged and swallowed so it can never abort the training run.
        """
        try:
            metrics, _ = self.evaluate_model(model, val_data, labels)
        except _TrainingStopped:
            # A stop during baseline is not a failure — let the caller end the
            # run cleanly as ``stopped`` rather than swallowing it here.
            raise
        except Exception as e:  # noqa: BLE001 - baseline must never break training
            logger.exception(f"[BASELINE EVAL FAILED] run_id={self.run_id} error={e}")
            return

        self._emit(
            {
                "type": "baseline_evaluation_completed",
                "run_id": self.run_id,
                "base_model": self.base_model_path,
                "metrics": {"per_label": metrics["per_label"]},
            }
        )

    def _run_evaluation(
        self,
        model,
        val_data: list[dict],
        labels: list[str],
        train_data: list[dict],
        total: int,
        train_pct: float,
        val_pct: float,
    ) -> None:
        """Evaluate the trained model, persist results, and emit completion."""
        # RUN EVALUATION HERE (AFTER TRAINING)
        metrics, evaluation_samples = self.evaluate_model(model, val_data, labels)

        # ----------------------------
        # SAVE EVALUATION RESULTS
        # ----------------------------
        eval_output_dir = Path.cwd() / "training_data"
        eval_output_dir.mkdir(parents=True, exist_ok=True)

        eval_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        evaluation_file = (
            eval_output_dir / f"evaluation_run{self.run_id}_{eval_timestamp}.json"
        )

        evaluation_payload = {
            "run_id": self.run_id,
            "base_model": self.base_model_path,
            "dataset_size": {
                "train": len(train_data),
                "val": len(val_data),
                "total": total,
            },
            "split_ratio": {
                "train_pct": train_pct,
                "val_pct": val_pct,
            },
            "labels": labels,
            "metrics": metrics,
            "evaluation_samples": evaluation_samples,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        with open(evaluation_file, "w", encoding="utf-8") as f:
            json.dump(evaluation_payload, f, indent=2, ensure_ascii=False)

        print(f"\nEvaluation saved to: {evaluation_file.resolve()}")

        print("\n========== EVALUATION RESULTS ==========\n")

        for label, scores in metrics["per_label"].items():
            print(f"[{label}]")
            print(f"  exact_f1   : {scores['exact_f1']:.4f}")
            print(f"  relaxed_f1 : {scores['relaxed_f1']:.4f}")
            print(f"  precision  : {scores['precision']:.4f}")
            print(f"  recall     : {scores['recall']:.4f}\n")

        self._emit(
            {
                "type": "evaluation_completed",
                "run_id": self.run_id,
                "metrics": {"per_label": metrics["per_label"]},
            }
        )

    def _save_model(self, model) -> None:
        """Persist the trained model to the shared models library and emit events."""
        # Persist trained models into the shared models library (mounted volume),
        # one folder per run, so they survive container restarts and can be served
        # by setting BIONER_MODEL to this path.
        models_dir = Path(os.environ.get("BIONER_MODELS_DIR", "/models"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        output_dir = models_dir / f"run-{self.run_id}-{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nSAVING MODEL TO: {output_dir}\n")
        print("Current working dir:", os.getcwd())

        output_path = Path(output_dir).resolve()

        print("Resolved output path:", output_path)
        print("Parent exists:", output_path.parent.exists())

        # save model
        model.save_pretrained(output_path)

        print("Model exists after save:", output_path.exists())
        print("Absolute path:", output_path.absolute())

        print("Saved files:")
        for f in output_path.iterdir():
            print(" -", f.resolve())

        self._output_path = str(output_path)
        self._set_status("completed")

        self._emit(
            {
                "type": "model_saved",
                "run_id": self.run_id,
                "output_path": str(output_path),
                "base_model": self.base_model_path,
                "engine": "gliner",
            }
        )

        self._emit(
            {
                "type": "completed",
                "run_id": self.run_id,
                "output_path": str(output_path),
            }
        )
