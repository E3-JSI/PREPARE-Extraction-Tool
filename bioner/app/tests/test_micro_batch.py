from app.training.gliner_trainer import GLiNERFinetuner


def _finetuner(batch_size: int) -> GLiNERFinetuner:
    return GLiNERFinetuner(
        run_id=1,
        base_model_path="x",
        training_data=[{}],
        train_batch_size=batch_size,
    )


def test_micro_batch_preserves_effective_batch():
    micro, accum = _finetuner(8)._compute_micro_batch()
    assert micro * accum == 8
    assert micro <= 2


def test_micro_batch_odd_sizes_fall_back_to_one():
    micro, accum = _finetuner(3)._compute_micro_batch()
    assert (micro, accum) == (1, 3)


def test_micro_batch_of_one_needs_no_accumulation():
    micro, accum = _finetuner(1)._compute_micro_batch()
    assert (micro, accum) == (1, 1)


def test_total_steps_mirror_hf_accumulation_floor():
    # HF Trainer computes updates/epoch as len_dataloader // accum (floored,
    # min 1); _compute_total_steps must announce the same count the run will
    # actually reach. Observed run: 339 train samples, batch 8 (micro 2 x
    # accum 4), 5 epochs -> HF ran 210 steps (ceil(339/2)=170; 170//4=42; x5).
    f = GLiNERFinetuner(
        run_id=1,
        base_model_path="x",
        training_data=[{}],
        train_batch_size=8,
        num_epochs=5,
    )
    assert f._compute_total_steps(train_size=339) == 210


def test_total_steps_without_accumulation_unchanged():
    # micro-batch 1 => accumulation 1 => plain ceil(n/batch)*epochs behavior.
    import math

    for n in (1, 9, 72, 73, 100):
        f = GLiNERFinetuner(
            run_id=1,
            base_model_path="x",
            training_data=[{}],
            train_batch_size=1,
            num_epochs=4,
        )
        assert f._compute_total_steps(train_size=n) == math.ceil(n / 1) * 4


def test_total_steps_tiny_run_still_at_least_one_per_epoch():
    # Fewer micro-batches than accumulation steps must not floor to zero.
    f = GLiNERFinetuner(
        run_id=1,
        base_model_path="x",
        training_data=[{}],
        train_batch_size=8,
        num_epochs=4,
    )
    assert f._compute_total_steps(train_size=2) == 4
