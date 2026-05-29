from sqlmodel import Session, select
from app.core.database import get_session
from app.models_db import Record, SourceTerm, TrainingEvaluation, TrainingMetric, TrainingEvaluation
from app.services.evaluation_service import evaluate_model


def load_training_data(db: Session, dataset_id: int, labels: list[str]):
    # Step 1: get records
    records = db.exec(
        select(Record)
        .where(Record.dataset_id == dataset_id)
    ).all()

    # Step 2: get source terms filtered by labels
    source_terms = db.exec(
        select(SourceTerm)
        .join(Record)
        .where(Record.dataset_id == dataset_id)
        .where(SourceTerm.label.in_(labels))
    ).all()

    return records, source_terms


def run_training(model, train_data, val_data, db, run_id):
    model.train(train_data)

    metrics = evaluate_model(model, val_data)

    save_metrics_to_db(db, run_id, metrics)
    
    save_evaluation(db, run_id, metrics)

    return metrics

def save_metrics_to_db(db, run_id, metrics):
    # 🔥 only store FULL evaluation metrics
    required = ["precision", "recall", "f1"]

    if any(metrics.get(k) is None for k in required):
        return  # skip incomplete updates (training logs etc.)

    db.add(
        TrainingMetric(
            run_id=run_id,
            epoch=metrics.get("epoch", 0),
            loss=metrics.get("loss"),
            accuracy=metrics.get("accuracy"),
            precision=metrics["precision"],
            recall=metrics["recall"],
            f1=metrics["f1"],
        )
    )
    db.commit()


def save_evaluation(db, run_id, metrics):
    db.add(
        TrainingEvaluation(
            run_id=run_id,
            precision=metrics["precision"],
            recall=metrics["recall"],
            f1=metrics["f1"],
            per_label=metrics["per_label"],
        )
    )
    db.commit()
    