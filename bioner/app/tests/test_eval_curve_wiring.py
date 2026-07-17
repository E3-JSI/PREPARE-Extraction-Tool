from app.core.settings import settings
from app.training.gliner_trainer import GLiNERFinetuner


def test_eval_steps_default_auto_targets_about_18_points(monkeypatch):
    # Default (BIONER_TRAIN_EVAL_STEPS=0) follows the standard practice of a
    # fixed number of eval points across the run (~18): 168 steps -> every 9.
    # Pinned explicitly because the ambient env may set a fixed interval.
    monkeypatch.setattr(settings, "BIONER_TRAIN_EVAL_STEPS", 0)
    f = GLiNERFinetuner(run_id=1, base_model_path="x", training_data=[{}])
    assert f._compute_eval_steps(total_steps=168) == 9
    # tiny runs still evaluate at least every step
    assert f._compute_eval_steps(total_steps=3) == 1


def test_eval_steps_explicit_interval_wins(monkeypatch):
    monkeypatch.setattr(settings, "BIONER_TRAIN_EVAL_STEPS", 1)
    f = GLiNERFinetuner(run_id=1, base_model_path="x", training_data=[{}])
    # dense per-step curve regardless of run size
    assert f._compute_eval_steps(total_steps=800) == 1


def test_eval_steps_negative_falls_back_to_auto(monkeypatch):
    monkeypatch.setattr(settings, "BIONER_TRAIN_EVAL_STEPS", -3)
    f = GLiNERFinetuner(run_id=1, base_model_path="x", training_data=[{}])
    assert f._compute_eval_steps(total_steps=168) == 9


def test_default_learning_rate_matches_reference_recipe():
    # Pins the reference-recipe LR — lowering it only masks a missing focal loss.
    f = GLiNERFinetuner(run_id=1, base_model_path="x", training_data=[{}])
    assert f.learning_rate == 5e-6


def test_total_steps_formula():
    f = GLiNERFinetuner(
        run_id=1,
        base_model_path="x",
        training_data=[{}],
        num_epochs=4,
        train_batch_size=8,
    )
    # 100 train items, effective batch 8 as micro-batches of 2 with 4x
    # accumulation -> HF floors updates/epoch: (ceil(100/2)=50)//4=12 * 4 = 48
    assert f._compute_total_steps(train_size=100) == 48
