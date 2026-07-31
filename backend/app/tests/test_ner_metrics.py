from app.interfaces import Entity
from app.library.ner_metrics import NERMetrics


def _ent(text, label, start, end):
    return Entity(text=text, label=label, start=start, end=end, score=1.0)


def test_exact_f1_perfect_match():
    true = [[_ent("aspirin", "Drug", 0, 7)]]
    pred = [[_ent("aspirin", "Drug", 0, 7)]]
    p, r, f1 = NERMetrics(["exact"]).evaluate_ner_performance(true, pred, "exact")
    assert (p, r, f1) == (1.0, 1.0, 1.0)


def test_relaxed_matches_partial_span_exact_does_not():
    true = [[_ent("aspirin 100mg", "Drug", 0, 13)]]
    pred = [[_ent("aspirin", "Drug", 0, 7)]]
    _, _, exact_f1 = NERMetrics(["exact"]).evaluate_ner_performance(true, pred, "exact")
    _, _, relaxed_f1 = NERMetrics(["relaxed"]).evaluate_ner_performance(true, pred, "relaxed")
    assert exact_f1 == 0.0
    assert relaxed_f1 == 1.0
