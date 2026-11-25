"""Deterministic document-level splitting for GLiNER training."""

from collections import Counter
from math import isfinite
from random import Random
from typing import Any, Dict, List, Sequence, Tuple


Document = Dict[str, Any]


def _stable_document_key(
    document: Document,
    original_index: int,
) -> tuple:
    """Return a stable key for deterministic ordering."""
    record_id = document.get("record_id")

    if isinstance(record_id, int):
        return (0, record_id, original_index)

    return (1, str(record_id), original_index)


def _document_labels(
    document: Document,
    selected_labels: Sequence[str],
) -> Tuple[str, ...]:
    """Return selected labels occurring in a document, once per label."""
    entity_labels = {
        entity[2].strip()
        for entity in (document.get("ner") or [])
        if (
            isinstance(entity, (list, tuple))
            and len(entity) >= 3
            and isinstance(entity[2], str)
            and entity[2].strip()
        )
    }

    return tuple(
        label
        for label in selected_labels
        if label in entity_labels
    )


def split_training_documents(
    documents: List[Document],
    val_ratio: float,
    selected_labels: Sequence[str],
    seed: int = 42,
) -> tuple[List[Document], List[Document]]:
    """Create a deterministic best-effort multilabel split.

    The function prioritizes label coverage and approximately preserves label
    and negative-document distributions. If perfect stratification is not
    possible, it still returns the requested split size.
    """
    if not documents:
        raise ValueError(
            "No eligible reviewed documents were found."
        )

    if not isfinite(val_ratio) or val_ratio < 0 or val_ratio >= 1:
        raise ValueError(
            "Validation ratio must be in the range [0, 1)."
        )

    if val_ratio == 0:
        return list(documents), []

    if len(documents) < 2:
        raise ValueError(
            "At least two eligible documents are required for validation."
        )

    labels = tuple(
        dict.fromkeys(
            label.strip()
            for label in selected_labels
            if isinstance(label, str) and label.strip()
        )
    )

    if not labels:
        raise ValueError(
            "At least one label is required for training."
        )

    document_labels = [
        _document_labels(document, labels)
        for document in documents
    ]

    label_totals = Counter(
        label
        for labels_in_document in document_labels
        for label in labels_in_document
    )

    train_size = int(len(documents) * (1 - val_ratio))
    train_size = max(
        1,
        min(train_size, len(documents) - 1),
    )
    validation_size = len(documents) - train_size
    validation_fraction = validation_size / len(documents)

    # Only labels occurring in at least two documents can be represented
    # in both training and validation.
    stratifiable_labels = {
        label
        for label in labels
        if label_totals[label] >= 2
    }

    label_targets = {
        label: label_totals[label] * validation_fraction
        for label in labels
        if label_totals[label] > 0
    }

    negative_total = sum(
        1
        for labels_in_document in document_labels
        if not labels_in_document
    )
    negative_target = negative_total * validation_fraction

    ranked_indices = sorted(
        range(len(documents)),
        key=lambda index: _stable_document_key(
            documents[index],
            index,
        ),
    )
    Random(seed).shuffle(ranked_indices)

    deterministic_rank = {
        index: rank
        for rank, index in enumerate(ranked_indices)
    }

    validation_indices: set[int] = set()
    validation_label_counts: Counter[str] = Counter()
    validation_negative_count = 0

    def training_loss_counts(index: int) -> tuple[int, int]:
        """Count strata that would disappear from training."""
        labels_in_document = document_labels[index]

        if not labels_in_document:
            loses_negative_stratum = (
                negative_total > 0
                and validation_negative_count + 1
                >= negative_total
            )

            if not loses_negative_stratum:
                return (0, 0)

            return (
                1 if negative_total == 1 else 0,
                1,
            )

        exhausted_labels = [
            label
            for label in labels_in_document
            if validation_label_counts[label] + 1
            >= label_totals[label]
        ]

        singleton_labels = sum(
            label_totals[label] == 1
            for label in exhausted_labels
        )

        return singleton_labels, len(exhausted_labels)

    def coverage_score(index: int) -> tuple:
        """Score how useful a document is for validation."""
        labels_in_document = document_labels[index]

        newly_covered_labels = [
            label
            for label in labels_in_document
            if (
                label in stratifiable_labels
                and validation_label_counts[label] == 0
            )
        ]

        missing_labels_covered = len(newly_covered_labels)
        missing_label_rarity = sum(
            1 / label_totals[label]
            for label in newly_covered_labels
        )

        distribution_improvement = 0.0

        for label in labels_in_document:
            target = label_targets[label]
            current = validation_label_counts[label]

            distribution_improvement += (
                abs(target - current)
                - abs(target - (current + 1))
            ) / label_totals[label]

        if not labels_in_document and negative_total:
            distribution_improvement += (
                abs(
                    negative_target
                    - validation_negative_count
                )
                - abs(
                    negative_target
                    - (validation_negative_count + 1)
                )
            ) / negative_total

        return (
            missing_labels_covered,
            missing_label_rarity,
            distribution_improvement,
            -deterministic_rank[index],
        )

    while len(validation_indices) < validation_size:
        remaining_indices = [
            index
            for index in ranked_indices
            if index not in validation_indices
        ]

        safe_indices = [
            index
            for index in remaining_indices
            if training_loss_counts(index)[1] == 0
        ]

        if safe_indices:
            best_index = max(
                safe_indices,
                key=coverage_score,
            )
        else:
            # Perfect separation is no longer possible. Choose the document
            # that removes the fewest useful strata from training.
            def fallback_score(index: int) -> tuple:
                singleton_losses, total_losses = (
                    training_loss_counts(index)
                )

                return (
                    -singleton_losses,
                    -total_losses,
                    *coverage_score(index),
                )

            best_index = max(
                remaining_indices,
                key=fallback_score,
            )

        validation_indices.add(best_index)
        labels_in_document = document_labels[best_index]

        if labels_in_document:
            validation_label_counts.update(
                labels_in_document
            )
        else:
            validation_negative_count += 1

    training_documents = [
        document
        for index, document in enumerate(documents)
        if index not in validation_indices
    ]
    validation_documents = [
        document
        for index, document in enumerate(documents)
        if index in validation_indices
    ]

    return training_documents, validation_documents