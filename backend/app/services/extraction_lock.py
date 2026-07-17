"""Instance-wide guard for blocking model switches during active extraction."""

from sqlmodel import Session, select

from app.models_db import ExtractionJob, LiveEvalJob

# Non-terminal extraction job states.
# ExtractionJob.status comment: pending|running|completed|failed
ACTIVE_EXTRACTION_STATES = ("pending", "running")


def any_extraction_job_active(db: Session) -> bool:
    """True if any extraction job is currently active anywhere in the instance."""
    row = db.exec(
        select(ExtractionJob.id).where(
            ExtractionJob.status.in_(ACTIVE_EXTRACTION_STATES)
        )
    ).first()
    return row is not None


def any_live_eval_job_active(db: Session) -> bool:
    """True if any live-eval job is currently active anywhere in the instance."""
    row = db.exec(
        select(LiveEvalJob.id).where(
            LiveEvalJob.status.in_(ACTIVE_EXTRACTION_STATES)
        )
    ).first()
    return row is not None


def any_ner_job_active(db: Session) -> bool:
    """True if any extraction OR live-eval job is active (they share bioner's
    single globally-active NER model, so neither may run while the other is)."""
    return any_extraction_job_active(db) or any_live_eval_job_active(db)
