"""Tests for TrainingJobManager stop -> restart handling.

Covers the deadlock fix: a stop during a slow pre-training phase must free the
job slot promptly (join-before-start) so a subsequent start succeeds, while a
genuinely-running job still rejects new starts. Uses a fake finetuner so tests
stay fast and need no real model download.
"""

import threading

import pytest

import app.training.job_manager as jm
from app.training.gliner_trainer import _TrainingStopped
from app.training.job_manager import StartResult, TrainingJobManager


class FakeFinetuner:
    """Drop-in stand-in for GLiNERFinetuner with a controllable ``run()``.

    ``run()`` blocks until ``release`` is set, checking ``_stop_event`` in a tight
    loop so a stop is observed within one tick — mimicking a cooperative stop
    checkpoint in a slow phase. It also tracks how many fakes run concurrently so
    tests can assert workers never overlap.
    """

    _concurrency_lock = threading.Lock()
    _active = 0
    max_concurrency = 0

    @classmethod
    def reset_concurrency(cls) -> None:
        with cls._concurrency_lock:
            cls._active = 0
            cls.max_concurrency = 0

    def __init__(self, run_id, base_model_path, training_data, eval_data=None, **kwargs):
        self.run_id = run_id
        self._status = "idle"
        self._status_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._release = threading.Event()
        self.started = threading.Event()
        self.stop_observed = False

    def request_stop(self) -> None:
        self._stop_event.set()

    def _emit(self, event) -> None:  # noqa: D401 - no-op for tests
        pass

    def _set_status(self, status) -> None:
        with self._status_lock:
            self._status = status

    def release(self) -> None:
        self._release.set()

    def run(self) -> None:
        self._set_status("running")
        with FakeFinetuner._concurrency_lock:
            FakeFinetuner._active += 1
            FakeFinetuner.max_concurrency = max(
                FakeFinetuner.max_concurrency, FakeFinetuner._active
            )
        self.started.set()
        try:
            while not self._release.is_set():
                if self._stop_event.is_set():
                    self.stop_observed = True
                    self._set_status("stopped")
                    return
                self._release.wait(0.005)
            self._set_status("completed")
        finally:
            with FakeFinetuner._concurrency_lock:
                FakeFinetuner._active -= 1


@pytest.fixture
def manager(monkeypatch):
    """Fresh singleton + fake finetuner per test; cleans up any live workers."""
    monkeypatch.setattr(jm, "GLiNERFinetuner", FakeFinetuner)
    # Shorten the join window so the "still stopping" path is quick to exercise.
    monkeypatch.setattr(jm, "JOIN_TIMEOUT_SECONDS", 0.5)
    TrainingJobManager._instance = None
    FakeFinetuner.reset_concurrency()
    mgr = TrainingJobManager()
    yield mgr
    # Release any still-running fakes and join their threads so a leaked worker
    # can't bleed into the next test.
    for job in list(mgr._jobs.values()):
        job.release()
    for t in list(mgr._threads.values()):
        t.join(timeout=2.0)
    TrainingJobManager._instance = None


def _start(mgr, run_id):
    return mgr.start_job(
        run_id=run_id,
        base_model_path="fake",
        training_data=[{"text": "x"}],
    )


def test_stop_during_slow_phase_frees_slot_for_next_start(manager):
    # (a) A stop during a simulated slow phase frees the slot; the next start_job
    # succeeds instead of deadlocking on a 409.
    assert _start(manager, 1) is StartResult.STARTED
    job1 = manager._jobs[1]
    assert job1.started.wait(2.0)

    assert manager.stop_job(1) is True

    # Immediately try to start a new run. start_job must join the winding-down
    # worker and then accept the new run.
    assert _start(manager, 2) is StartResult.STARTED
    assert job1.stop_observed is True
    assert manager._jobs[2].started.wait(2.0)


def test_start_while_genuinely_running_is_rejected(manager):
    # (b) A start while a job is genuinely running (not stopped) is rejected.
    assert _start(manager, 1) is StartResult.STARTED
    assert manager._jobs[1].started.wait(2.0)

    assert _start(manager, 2) is StartResult.BUSY
    # Original job untouched; run 2 never registered.
    assert 2 not in manager._jobs


def test_join_before_start_never_overlaps_two_workers(manager):
    # (c) Join-before-start must never let two workers run at once.
    assert _start(manager, 1) is StartResult.STARTED
    assert manager._jobs[1].started.wait(2.0)

    assert manager.stop_job(1) is True
    assert _start(manager, 2) is StartResult.STARTED
    assert manager._jobs[2].started.wait(2.0)

    # The stopped worker was joined before the new one started, so at no point
    # did two fakes execute run() simultaneously.
    assert FakeFinetuner.max_concurrency == 1


def test_start_returns_stopping_when_worker_wont_wind_down(manager, monkeypatch):
    # A stop-requested worker that never reaches a terminal status within the
    # join window yields STOPPING (not BUSY) so the frontend can advise a retry.
    class StubbornFinetuner(FakeFinetuner):
        def run(self) -> None:
            self._set_status("running")
            self.started.set()
            # Ignore the stop event entirely; only ``release`` ends it.
            self._release.wait(10.0)
            self._set_status("stopped")

    monkeypatch.setattr(jm, "GLiNERFinetuner", StubbornFinetuner)

    assert _start(manager, 1) is StartResult.STARTED
    job1 = manager._jobs[1]
    assert job1.started.wait(2.0)

    assert manager.stop_job(1) is True
    assert _start(manager, 2) is StartResult.STOPPING
    assert 2 not in manager._jobs

    # Let the stubborn worker finish so the fixture can join it.
    job1.release()


class _StopOnCallModel:
    """Fake GLiNER model whose ``predict_entities`` sets the stop event.

    Records how many times it is called so tests can assert the eval loop bails
    within one item of the stop request.
    """

    def __init__(self, stop_event, stop_after):
        self._stop_event = stop_event
        self._stop_after = stop_after
        self.calls = 0

    def predict_entities(self, text, labels, threshold=0.5):
        self.calls += 1
        if self.calls >= self._stop_after:
            self._stop_event.set()
        return []


def test_eval_loop_stop_check_aborts_promptly():
    # (d) The eval-loop stop check aborts within one item once the stop is set.
    from app.training.gliner_trainer import GLiNERFinetuner

    f = GLiNERFinetuner(run_id=1, base_model_path="x", training_data=[{"text": "a"}])
    dataset = [{"text": f"item {i}", "ner": []} for i in range(50)]

    model = _StopOnCallModel(f._stop_event, stop_after=1)

    with pytest.raises(_TrainingStopped):
        f.evaluate_model(model, dataset, labels=["DISEASE"])

    # Predicted the first item, set the stop, then bailed at the top of item 2 —
    # no further predictions over the remaining 48 items.
    assert model.calls == 1


def test_eval_loop_stop_check_bails_before_first_item():
    from app.training.gliner_trainer import GLiNERFinetuner

    f = GLiNERFinetuner(run_id=1, base_model_path="x", training_data=[{"text": "a"}])
    f.request_stop()
    dataset = [{"text": f"item {i}", "ner": []} for i in range(10)]

    model = _StopOnCallModel(f._stop_event, stop_after=1)
    with pytest.raises(_TrainingStopped):
        f.evaluate_model(model, dataset, labels=["DISEASE"])

    # Stop was already set, so predict_entities is never called.
    assert model.calls == 0


def test_baseline_evaluation_reraises_stop(monkeypatch):
    from app.training.gliner_trainer import GLiNERFinetuner

    f = GLiNERFinetuner(run_id=1, base_model_path="x", training_data=[{"text": "a"}])

    def _stopped(*args, **kwargs):
        raise _TrainingStopped()

    monkeypatch.setattr(f, "evaluate_model", _stopped)

    with pytest.raises(_TrainingStopped):
        f._run_baseline_evaluation(model=object(), val_data=[], labels=["X"])


def test_baseline_evaluation_swallows_other_errors(monkeypatch):
    from app.training.gliner_trainer import GLiNERFinetuner

    f = GLiNERFinetuner(run_id=1, base_model_path="x", training_data=[{"text": "a"}])

    def _boom(*args, **kwargs):
        raise RuntimeError("baseline blew up")

    monkeypatch.setattr(f, "evaluate_model", _boom)

    # Non-stop failures must never propagate out of the best-effort baseline.
    f._run_baseline_evaluation(model=object(), val_data=[], labels=["X"])
