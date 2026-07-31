"""Tests for step-indexed training metrics (train + eval loss)."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.models_db import Dataset, TrainingMetric, TrainingRun, User
from app.services import training_service


def _make_run(db: Session) -> TrainingRun:
    u = User(username="t", hashed_password="h")
    db.add(u)
    db.commit()
    db.refresh(u)
    ds = Dataset(name="d", labels=[], user_id=u.id)
    db.add(ds)
    db.commit()
    db.refresh(ds)
    r = TrainingRun(dataset_id=ds.id, base_model="m", labels=["Drug"], val_ratio=0.1)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_add_step_metric_persists_step_and_eval_loss():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        r = _make_run(db)
        training_service.add_step_metric(db, r.id, step=10, epoch=1, loss=0.5)
        training_service.add_step_metric(db, r.id, step=20, epoch=1, eval_loss=0.42)
        rows = db.exec(
            select(TrainingMetric)
            .where(TrainingMetric.run_id == r.id)
            .order_by(TrainingMetric.step)
        ).all()
        assert [m.step for m in rows] == [10, 20]
        assert rows[0].loss == 0.5 and rows[0].eval_loss is None
        assert rows[1].eval_loss == 0.42 and rows[1].loss is None
    SQLModel.metadata.drop_all(engine)
