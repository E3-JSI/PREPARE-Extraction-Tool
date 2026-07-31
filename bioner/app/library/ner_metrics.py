from difflib import SequenceMatcher
from typing import List, Literal, Optional, Tuple, Union

from app.interfaces import Entity


def _compute_precision_recall_f1(tp: int, fp: int, fn: int) -> Tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
    return precision, recall, f1


def _entity_matches_exact(true_ent: Entity, pred_ent: Entity) -> bool:
    return (
        true_ent.label == pred_ent.label
        and true_ent.start == pred_ent.start
        and true_ent.end == pred_ent.end
    )


def _entity_matches_relaxed(true_ent: Entity, pred_ent: Entity) -> bool:
    if true_ent.label != pred_ent.label:
        return False

    true_contains_pred = true_ent.start <= pred_ent.start and true_ent.end >= pred_ent.end
    pred_contains_true = pred_ent.start <= true_ent.start and pred_ent.end >= true_ent.end
    return true_contains_pred or pred_contains_true


def _entity_matches_overlap(true_ent: Entity, pred_ent: Entity) -> bool:
    if true_ent.label != pred_ent.label:
        return False

    return max(true_ent.start, pred_ent.start) < min(true_ent.end, pred_ent.end)


def _match_entities(
    true_ents: List[Entity],
    pred_ents: List[Entity],
    match_fn,
    label: Optional[str] = None,
) -> Tuple[int, int, int]:
    filtered_true = [ent for ent in true_ents if label is None or ent.label == label]
    filtered_pred = [ent for ent in pred_ents if label is None or ent.label == label]

    if not filtered_true and not filtered_pred:
        return 0, 0, 0

    matched_pred_indices: set[int] = set()
    tp = 0

    for true_ent in filtered_true:
        for index, pred_ent in enumerate(filtered_pred):
            if index in matched_pred_indices:
                continue
            if match_fn(true_ent, pred_ent):
                matched_pred_indices.add(index)
                tp += 1
                break

    fp = len(filtered_pred) - tp
    fn = len(filtered_true) - tp
    return tp, fp, fn


def _exact_ner_evaluation(
    true_ents: List[Entity], pred_ents: List[Entity], label: str = None
) -> Tuple[int, int, int]:
    return _match_entities(true_ents, pred_ents, _entity_matches_exact, label=label)


def _relaxed_ner_evaluation(
    true_ents: List[Entity],
    pred_ents: List[Entity],
    label: str = None,
) -> Tuple[int, int, int]:
    return _match_entities(true_ents, pred_ents, _entity_matches_relaxed, label=label)


def _overlap_ner_evaluation(
    true_ents: List[Entity],
    pred_ents: List[Entity],
    label: str = None,
) -> Tuple[int, int, int]:
    return _match_entities(true_ents, pred_ents, _entity_matches_overlap, label=label)


def _bertscore_ner_evaluation(
    true_ents: List[Entity],
    pred_ents: List[Entity],
    label: str = None,
) -> Tuple[float, float, float, int]:
    filtered_true = [ent for ent in true_ents if label is None or ent.label == label]
    filtered_pred = [ent for ent in pred_ents if label is None or ent.label == label]

    if not filtered_true and not filtered_pred:
        return 0.0, 0.0, 0.0, 0
    if not filtered_true or not filtered_pred:
        return 0.0, 0.0, 0.0, 1

    def _best_score(ent: Entity, candidates: List[Entity]) -> float:
        best = 0.0
        for candidate in candidates:
            if ent.label != candidate.label:
                continue
            score = SequenceMatcher(
                None,
                ent.text.lower().strip(),
                candidate.text.lower().strip(),
            ).ratio()
            if score > best:
                best = score
        return best

    # Recall: for each true entity, best match among predictions
    best_true_scores = [_best_score(true_ent, filtered_pred) for true_ent in filtered_true]
    # Precision: for each prediction, best match among true entities
    best_pred_scores = [_best_score(pred_ent, filtered_true) for pred_ent in filtered_pred]

    recall = sum(best_true_scores) / len(filtered_true) if filtered_true else 0.0
    precision = sum(best_pred_scores) / len(filtered_pred) if filtered_pred else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
    return precision, recall, f1, 1


class NERMetrics:

    def __init__(self, metrics: List[Literal["exact", "relaxed", "overlap", "bertscore"]]):
        self.metrics = metrics

    def evaluate_ner_performance(
        self,
        true_ents: List[List[Entity]],
        pred_ents: List[List[Entity]],
        match_type: Union[Literal["exact"], Literal["relaxed"], Literal["overlap"], Literal["bertscore"]] = "exact",
        label: str = None,
    ) -> Tuple[float, float, float]:
        if len(true_ents) != len(pred_ents):
            raise ValueError("The number of true and predicted entities must be the same.")

        if match_type not in ["exact", "relaxed", "overlap", "bertscore"]:
            raise ValueError(f"Unknown match_type method: {match_type}")

        if match_type == "bertscore":
            precision_total = 0.0
            recall_total = 0.0
            f1_total = 0.0
            count = 0

            for true_ent, pred_ent in zip(true_ents, pred_ents):
                precision, recall, f1, used = _bertscore_ner_evaluation(true_ent, pred_ent, label=label)
                precision_total += precision
                recall_total += recall
                f1_total += f1
                count += used

            if count == 0:
                return 0.0, 0.0, 0.0

            return precision_total / count, recall_total / count, f1_total / count

        if match_type == "exact":
            eval_func = _exact_ner_evaluation
        elif match_type == "relaxed":
            eval_func = _relaxed_ner_evaluation
        else:
            eval_func = _overlap_ner_evaluation

        tp, fp, fn = 0, 0, 0
        for true_ent, pred_ent in zip(true_ents, pred_ents):
            _tp, _fp, _fn = eval_func(true_ent, pred_ent, label=label)
            tp += _tp
            fp += _fp
            fn += _fn

        return _compute_precision_recall_f1(tp, fp, fn)

    def sentence_errors(
        self,
        true_ents: List[Entity],
        pred_ents: List[Entity],
        match_type: Literal["exact", "relaxed", "overlap"] = "relaxed",
        label: Optional[str] = None,
    ) -> Tuple[List[Entity], List[Entity]]:
        """Return ``(false_positives, false_negatives)`` for one sentence.

        Uses the same greedy matching as the aggregate scores, so the returned
        counts line up with the precision/recall reported for ``label``. A false
        positive is a predicted entity with no matching gold entity; a false
        negative is a gold entity with no matching prediction.

        Args:
            true_ents (List[Entity]): Gold entities for one sentence.
            pred_ents (List[Entity]): Predicted entities for one sentence.
            match_type: Matching strictness (``exact``, ``relaxed`` or ``overlap``).
            label (Optional[str]): Restrict to a single label, or all when None.

        Returns:
            Tuple[List[Entity], List[Entity]]: ``(false_positives, false_negatives)``.
        """
        if match_type == "exact":
            match_fn = _entity_matches_exact
        elif match_type == "relaxed":
            match_fn = _entity_matches_relaxed
        elif match_type == "overlap":
            match_fn = _entity_matches_overlap
        else:
            raise ValueError(f"Unsupported match_type for errors: {match_type}")

        filtered_true = [ent for ent in true_ents if label is None or ent.label == label]
        filtered_pred = [ent for ent in pred_ents if label is None or ent.label == label]

        matched_pred: set[int] = set()
        matched_true: set[int] = set()
        for ti, true_ent in enumerate(filtered_true):
            for pi, pred_ent in enumerate(filtered_pred):
                if pi in matched_pred:
                    continue
                if match_fn(true_ent, pred_ent):
                    matched_pred.add(pi)
                    matched_true.add(ti)
                    break

        false_positives = [p for pi, p in enumerate(filtered_pred) if pi not in matched_pred]
        false_negatives = [t for ti, t in enumerate(filtered_true) if ti not in matched_true]
        return false_positives, false_negatives