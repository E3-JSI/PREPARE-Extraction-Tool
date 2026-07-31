"""Shared numpy-backed vector math helpers.

Small utilities for cosine similarity and mean-vector (centroid) computation,
used by the clustering / merge-suggestion logic in several backend modules.
"""

from typing import List, Sequence

import numpy as np


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute the cosine similarity between two vectors.

    Returns 0.0 when either vector has zero magnitude (mirrors the previous
    pure-Python implementations, which guarded against a zero denominator).

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity in [-1.0, 1.0], or 0.0 if either norm is zero.
    """
    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def mean_vector(vectors: Sequence[Sequence[float]]) -> List[float]:
    """Compute the mean vector (centroid) of a collection of vectors.

    Args:
        vectors: A sequence of equal-length vectors.

    Returns:
        The element-wise mean as a list of floats, or an empty list when no
        vectors are provided (mirrors the previous implementations).
    """
    if len(vectors) == 0:
        return []
    return np.asarray(vectors, dtype=float).mean(axis=0).tolist()


# Alias kept for call sites that referred to this as "centroid".
centroid = mean_vector
