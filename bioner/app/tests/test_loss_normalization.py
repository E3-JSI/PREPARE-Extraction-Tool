import torch

from app.training.gliner_trainer import _per_positive_mean_loss


def test_reported_loss_is_summed_loss_per_positive_span():
    """The reported loss is the sum-reduced loss divided by the positive count.

    With focal loss the >99.9%-negative score grid contributes almost nothing,
    so a per-element mean flattens to ~1e-3; normalizing per positive span
    (RetinaNet convention) keeps the curve in a familiar range without altering
    the (summed) gradient signal.
    """
    summed = torch.tensor(440.0)

    reported = _per_positive_mean_loss(summed, 40)

    assert torch.allclose(reported, summed / 40)
    # Lands in a sane single/low-double-digit range, not ~1e-3.
    assert 1.0 < reported.item() < 100.0


def test_normalized_loss_accepts_plain_floats():
    # Works for python scalars too (e.g. an already-detached float).
    assert _per_positive_mean_loss(400.0, 50) == 8.0


def test_zero_positives_is_safe():
    # Batches with no positive spans must not divide by zero.
    assert _per_positive_mean_loss(123.0, 0) == 123.0
