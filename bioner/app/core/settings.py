from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
# ======================================================
# Settings configuration
# ======================================================


class Settings(BaseSettings):
    """Bioner service settings.

    Attributes:
        BACKEND_HOST (str): Base URL of the backend service used for training
            event callbacks. Defaults to localhost for local runs; overridden to
            the compose service name (http://backend:8000) in docker-compose.
        BIONER_TRAIN_MAX_TOKENS (int): Hard cap on tokens per training window.
            Long records are trimmed to span-centred windows of at most this many
            tokens before reaching the GLiNER collator, bounding the
            ``seq_len x span_width x num_classes`` score tensor (which otherwise
            makes the first CPU step crawl).
        BIONER_TRAIN_CONTEXT_PAD (int): Tokens of context kept on each side of a
            span group when trimming long records to training windows.
        BIONER_TRAIN_MICRO_BATCH (int): Cap on the per-forward micro-batch size
            during fine-tuning. The effective batch (``train_batch_size``) is
            kept via gradient accumulation, so only activation memory shrinks.
            CPU training with a full batch of 8 peaked above 14 GB RSS and got
            the service OOM-killed by the kernel.
        BIONER_TRAIN_EVAL_STEPS (int): Eval-loss interval in optimizer steps.
            0 (default) = auto: ~18 evenly spaced eval points across the run,
            the standard practice, keeping eval cost bounded as datasets grow.
            Set >= 1 to force a fixed interval (1 = evaluate every step for a
            fully dense curve; each eval pass reads the whole validation split,
            which on CPU can take several times longer than a train step).
        BIONER_TRAIN_OVERHEAD_MB (int): Pre-flight estimate of training memory
            beyond ``3.5 x weight bytes`` (activations, tokenizer, runtime).
            Lowering it admits borderline models that may then abort mid-run.
        BIONER_TRAIN_MIN_FREE_MB (int): Abort an in-flight run when available
            memory drops below this. Must exceed one training step's transient
            allocation (hundreds of MB), or the OS OOM-kills the process before
            the guard can abort cleanly.
        TRAINING_STOP_JOIN_TIMEOUT (float): Seconds to wait for a stop-requested
            training worker to wind down before a new run is reported as still
            stopping (409 TRAINING_STOPPING). Kept short so the API stays
            responsive; the client retries.
    """

    BACKEND_HOST: str = "http://localhost:8000"
    BIONER_TRAIN_MAX_TOKENS: int = 256
    BIONER_TRAIN_CONTEXT_PAD: int = 64
    BIONER_TRAIN_MICRO_BATCH: int = 2
    BIONER_TRAIN_EVAL_STEPS: int = 0
    BIONER_TRAIN_OVERHEAD_MB: int = 1024
    BIONER_TRAIN_MIN_FREE_MB: int = 512

    TRAINING_STOP_JOIN_TIMEOUT: float = 5.0

    # ======================================================
    # Environment setting
    # ======================================================

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
