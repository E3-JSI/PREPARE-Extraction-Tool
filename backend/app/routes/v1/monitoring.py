# app/routes/v1/monitoring.py
import asyncio
import json
import os
import random
import threading
import time
from typing import List
from xml.parsers.expat import model
from transformers import AutoTokenizer, AutoModelForTokenClassification
from torch.optim import AdamW
from gliner import GLiNER
from seqeval.metrics import classification_report, f1_score, precision_score, recall_score
from app.models_db import TrainingEvaluation, TrainingRun
from sqlmodel import select

from transformers import AutoModelForTokenClassification
from torch.optim import AdamW
import torch
from transformers import AutoTokenizer 
 
from sqlmodel import Session, select
from gliner import GLiNER
import torch
from tqdm import tqdm
from sqlmodel import select
from sqlalchemy import func 
from gliner import GLiNER

from jose import jwt, JWTError

from sqlmodel import Session
from app.core.database import engine

from fastapi import APIRouter, BackgroundTasks, Depends, WebSocket, WebSocketDisconnect
from sqlmodel import Session
from app.services.training_service import load_training_data
from app.schemas import TrainingRequest

from app.core.settings import settings
from app.core.database import get_session
from app.models_db import ModelArtifact, TrainingMetric, TrainingRun, User, TrainingEvaluation
from app.models_db import (
    Dataset,
    Record,
    SourceTerm,
    SentenceSegment,
    Cluster,
    ExtractionJob,
)
from app.routes.v1.auth import get_current_user

# =========================
# Setup
# =========================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
router = APIRouter()

# =========================
# Logging
# =========================
import logging

os.makedirs("logs", exist_ok=True)
log_file = os.path.join("logs", "monitoring.log")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if not logger.handlers:
    fh = logging.FileHandler(log_file)
    ch = logging.StreamHandler()

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

logger.info("monitoring.py logger initialized")

# =========================
# Global state
# =========================
active_connections: List[WebSocket] = []

training_state = {
    "running": False,
    "current_epoch": 0,
    "metrics": [],
    "stop_requested": False,
}

training_thread: threading.Thread | None = None

# 🔥 CRITICAL
main_loop = None

# =========================
# Broadcast helper
# =========================
async def broadcast_metric(data: dict):
    logger.info(f"Broadcasting: {data}")

    dead_connections = []

    for ws in active_connections:
        try:
            await ws.send_json(data)
            logger.info("Sent to client")
        except Exception as e:
            logger.error(f"Send failed: {e}")
            dead_connections.append(ws)

    for ws in dead_connections:
        active_connections.remove(ws)

# =========================
# WebSocket endpoint
# =========================
@router.websocket("/ws/training")
async def training_ws(websocket: WebSocket):
    global main_loop

    main_loop = asyncio.get_running_loop()

    token = websocket.query_params.get("token")
    if not token:
        logger.info("Rejected: no token")
        await websocket.close(code=1008)
        return

    

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username = payload.get("sub")

        if not username:
            logger.info("Rejected: no username")
            await websocket.close(code=1008)
            return

    except JWTError:
        logger.info("Rejected: invalid token")
        await websocket.close(code=1008)
        return

    await websocket.accept()
    active_connections.append(websocket)

    logger.info(f"WebSocket connected: {username}")
    logger.info(f"Active connections: {len(active_connections)}")

    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.info(f"Disconnected: {username}")
        active_connections.remove(websocket)

# =========================
# Training thread (SIMULATED)
# =========================

def encode_ner_example(text, entities, tokenizer, label2id):
    encoding = tokenizer(
        text,
        return_offsets_mapping=True,
        truncation=True,
        padding="max_length",
        max_length=256
    )

    input_ids = encoding["input_ids"]
    offsets = encoding["offset_mapping"]

    labels = [-100] * len(input_ids)

    for ent in entities:
        start, end, label = ent["start"], ent["end"], ent["label"]
        label_id = label2id[label]

        found = False

        for i, (s, e) in enumerate(offsets):

            if s == e:
                continue

            # token overlaps entity span (IMPORTANT FIX)
            if not (e <= start or s >= end):
                if not found:
                    labels[i] = label_id  # B
                    found = True
                else:
                    labels[i] = label_id  # I

    # 🔥 safety check
    if all(l == -100 for l in labels):
        print("WARNING: sample has no labels!")

    encoding["labels"] = labels

    return {
        "input_ids": input_ids,
        "attention_mask": encoding["attention_mask"],
        "labels": labels
    }

def emit_training_update(payload: dict):
    global main_loop

    if not main_loop:
        return

    asyncio.run_coroutine_threadsafe(
        broadcast_metric(payload),
        main_loop
    )

def to_python_types(obj):
    import numpy as np

    if isinstance(obj, dict):
        return {k: to_python_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_python_types(v) for v in obj]
    elif isinstance(obj, (np.float32, np.float64)):
        return float(obj)
    elif isinstance(obj, (np.int32, np.int64)):
        return int(obj)
    else:
        return obj

def split_dataset(dataset, val_ratio=0.2):
    random.shuffle(dataset)
    split_idx = int(len(dataset) * (1 - val_ratio))
    return dataset[:split_idx], dataset[split_idx:]

def run_training_sync(dataset_id: int, run_id: int, labels: list[str]):
    import time

    tokenizer = AutoTokenizer.from_pretrained("bert-base-cased")
    #if not labels:
    #    raise ValueError("Labels cannot be empty")

    db = Session(engine)
    try:
        if not labels:
            emit_training_update({
            "type": "error",
            "message": "Labels cannot be empty"
            })
            return
        # ======================
        # Load data
        # ======================
        records = db.exec(
            select(Record).where(Record.dataset_id == dataset_id)
        ).all()

        source_terms = db.exec(
            select(SourceTerm)
            .join(Record)
            .where(Record.dataset_id == dataset_id)
            .where(SourceTerm.label.in_(labels))
        ).all()

        label2id = {l: i for i, l in enumerate(labels)}
        id2label = {i: l for l, i in label2id.items()}

        full_data = build_ner_dataset(records, source_terms, tokenizer, label2id)

        train_data, val_data = split_dataset(full_data)

        emit_training_update({
            "type": "data_split",
            "train_size": len(train_data),
            "val_size": len(val_data)
        })

        emit_training_update({
            "type": "training_start",
            "run_id": run_id,
            "dataset_size": len(train_data)
        })

        print("FULL DATA SIZE:", len(full_data))
        print("TRAIN SIZE:", len(train_data))
        print("VAL SIZE:", len(val_data))

        # ======================
        # Model
        # ======================
        model = AutoModelForTokenClassification.from_pretrained(
            "bert-base-cased",
            num_labels=len(labels),
            id2label={i: l for l, i in label2id.items()},
            label2id=label2id
        )

        optimizer = AdamW(model.parameters(), lr=2e-5)
        model.train()

        # ======================
        # TRAIN LOOP
        # ======================
        epochs = 1
        best_f1 = 0
        patience = 2
        no_improve_epochs = 0

        for epoch in range(epochs):
            total_loss = 0.0

            emit_training_update({
                "type": "epoch_start",
                "epoch": epoch + 1,
                "total_epochs": epochs
            })

            for i, sample in enumerate(train_data):

                input_ids = torch.tensor([sample["input_ids"]])
                attention_mask = torch.tensor([sample["attention_mask"]])
                labels_tensor = torch.tensor([sample["labels"]])

                outputs = model(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    labels=labels_tensor
                )

                loss = outputs.loss

                # 🚀 skip NaN losses
                if torch.isnan(loss):
                    continue

                loss.backward()

                # 🚀 ADD THIS LINE HERE
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)

                optimizer.step()
                optimizer.zero_grad()

                total_loss += loss.item()

                # 🔥 LIVE BATCH UPDATE (THIS IS WHAT YOU WERE MISSING)
                if i % 10 == 0:
                    emit_training_update({
                        "type": "batch_update",
                        "epoch": epoch + 1,
                        "batch": i,
                        "loss": float(loss.item())
                    })

            avg_loss = total_loss / max(len(train_data), 1)

            # 🔥 VALIDATION
            eval_results = evaluate_model(model, val_data, id2label)

            emit_training_update({
                "type": "epoch_end",
                "epoch": epoch + 1,
                "loss": float(avg_loss),
                "val_f1": float(eval_results["f1"]),
            })

            # 🔥 EARLY STOPPING LOGIC
            if eval_results["f1"] > best_f1:
                best_f1 = eval_results["f1"]
                no_improve_epochs = 0
            else:
                no_improve_epochs += 1

            if no_improve_epochs >= patience:
                emit_training_update({
                    "type": "early_stopping",
                    "epoch": epoch + 1
                })
                break

            #emit_training_update({
            #    "type": "epoch_end",
            #    "epoch": epoch + 1,
            #    "loss": float(avg_loss)
            #})

            db.add(TrainingMetric(
                run_id=run_id,
                epoch=epoch + 1,
                loss=float(avg_loss),
                precision=0,
                recall=0,
                f1=0
            ))
            db.commit()

        # ======================
        # SAVE MODEL
        # ======================
        model_path = f"models/model_{run_id}"
        model.save_pretrained(model_path)
        tokenizer.save_pretrained(model_path)

        # ======================
        # FINAL EVALUATION
        # ======================
        final_eval = evaluate_model(model, val_data, id2label)
        db.add(TrainingEvaluation(
            run_id=run_id,
            precision=float(final_eval["precision"]),
            recall=float(final_eval["recall"]),
            f1=float(final_eval["f1"]),
            per_label=to_python_types(final_eval["per_label"])
        ))

        db.commit()

        emit_training_update({
            "type": "evaluation",
            "precision": float(final_eval["precision"]),
            "recall": float(final_eval["recall"]),
            "f1": float(final_eval["f1"]),
            "per_label": to_python_types(final_eval["per_label"])
        })


    finally:
        db.close()


def evaluate_model(model, dataset, id2label):
    model.eval()

    true_labels = []
    pred_labels = []

    for sample in dataset:
        inputs = {
            "input_ids": torch.tensor([sample["input_ids"]]),
            "attention_mask": torch.tensor([sample["attention_mask"]])
        }

        with torch.no_grad():
            outputs = model(**inputs)

        preds = outputs.logits.argmax(-1).squeeze().tolist()
        labels = sample["labels"]

        true_seq = []
        pred_seq = []

        for p, l in zip(preds, labels):
            if l == -100:
                continue

            true_seq.append(id2label[l])
            pred_seq.append(id2label[p])

        if true_seq:
            true_labels.append(true_seq)
            pred_labels.append(pred_seq)

    # 🚀 ADD THIS BLOCK
    if not true_labels:
        return {
            "precision": 0,
            "recall": 0,
            "f1": 0,
            "per_label": {}
        }

    report = classification_report(true_labels, pred_labels, output_dict=True)

    return {
        "precision": precision_score(true_labels, pred_labels),
        "recall": recall_score(true_labels, pred_labels),
        "f1": f1_score(true_labels, pred_labels),
        "per_label": report
    }

 
@router.post("/start")
async def start_training(
    request: TrainingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    dataset_id = request.dataset_id
    labels = request.labels

    run = TrainingRun(
        dataset_id=dataset_id,
        user_id=current_user.id,
        status="running",
        total_epochs=5
    )

    db.add(run)
    db.commit()
    db.refresh(run)

    threading.Thread(
        target=run_training_sync,
        args=(dataset_id, run.id, labels),
        daemon=True
    ).start()

    return {"run_id": run.id}


def build_ner_dataset(records, source_terms, tokenizer, label2id):
    dataset = []

    terms_by_record = {}
    for t in source_terms:
        terms_by_record.setdefault(t.record_id, []).append(t)

    for r in records:
        entities = []

        for t in terms_by_record.get(r.id, []):
            entities.append({
                "start": t.start_position,
                "end": t.end_position,
                "label": t.label
            })

        encoded = encode_ner_example(r.text, entities, tokenizer, label2id)
        empty_count = 0
        # 🚀 SKIP EMPTY SAMPLES HERE
        if all(l == -100 for l in encoded["labels"]):
            empty_count += 1
            continue
        print("EMPTY SAMPLES:", empty_count)

        dataset.append(encoded)

    return dataset

@router.post("/stop")
async def stop_training():
    if training_state["running"]:
        training_state["stop_requested"] = True
        return {"message": "Stop requested"}
    return {"message": "No training in progress"}


from sqlmodel import select, func

@router.get("/datasets/{dataset_id}/full-stats")
def get_full_stats(dataset_id: int, db: Session = Depends(get_session)):

    total_records = db.exec(
        select(func.count(Record.id))
        .where(Record.dataset_id == dataset_id)
    ).one()

    total_terms = db.exec(
        select(func.count(SourceTerm.id))
        .join(Record, Record.id == SourceTerm.record_id)
        .where(Record.dataset_id == dataset_id)
    ).one()

    label_distribution = db.exec(
        select(SourceTerm.label, func.count(SourceTerm.id))
        .join(Record, Record.id == SourceTerm.record_id)
        .where(Record.dataset_id == dataset_id)
        .group_by(SourceTerm.label)
    ).all()

    return {
        "totalRecords": total_records,
        "totalTerms": total_terms,
        "labelDistribution": {
            label: count for label, count in label_distribution
        }
    }


@router.get("/evaluations")
def get_all_evaluations(db: Session = Depends(get_session)):
    rows = db.exec(
        select(TrainingEvaluation, TrainingRun)
        .join(TrainingRun, TrainingRun.id == TrainingEvaluation.run_id)
    ).all()

    return [
        {
            "run_id": r.TrainingEvaluation.run_id,
            "dataset_id": r.TrainingRun.dataset_id,
            "precision": r.TrainingEvaluation.precision,
            "recall": r.TrainingEvaluation.recall,
            "f1": r.TrainingEvaluation.f1,
            "per_label": r.TrainingEvaluation.per_label,
        }
        for r in rows
    ]


@router.get("/runs/{run_id}/evaluation")
def get_evaluation(run_id: int, session: Session = Depends(get_session)):
    evaluation = session.exec(
        select(TrainingEvaluation)
        .where(TrainingEvaluation.run_id == run_id)
    ).first()

    if not evaluation:
        return {
            "run_id": run_id,
            "precision": 0,
            "recall": 0,
            "f1": 0,
            "per_label": {},
        }

    return {
        "run_id": evaluation.run_id,
        "precision": evaluation.precision,
        "recall": evaluation.recall,
        "f1": evaluation.f1,
        "per_label": evaluation.per_label,
    }


@router.get("/datasets/{dataset_id}/runs")
def get_runs_for_dataset(dataset_id: int, session: Session = Depends(get_session)):
    runs = session.exec(
        select(TrainingRun)
        .where(TrainingRun.dataset_id == dataset_id)
        .order_by(TrainingRun.id.desc())
    ).all()

    return [
        {
            "run_id": run.id,
            "dataset_id": run.dataset_id,
        }
        for run in runs
    ]


@router.get("/evaluations")
def get_all_evaluations(session: Session = Depends(get_session)):
    rows = session.exec(
        select(TrainingEvaluation, TrainingRun)
        .join(TrainingRun, TrainingRun.id == TrainingEvaluation.run_id)
    ).all()

    return [
        {
            "run_id": eval.run_id,
            "dataset_id": run.dataset_id,
            "precision": eval.precision,
            "recall": eval.recall,
            "f1": eval.f1,
            "per_label": eval.per_label,
        }
        for eval, run in rows
    ]


@router.get("/datasets/{dataset_id}/runs/evaluations")
def get_dataset_runs_evaluations(
    dataset_id: int,
    session: Session = Depends(get_session),
):
    runs = session.exec(
        select(TrainingRun).where(TrainingRun.dataset_id == dataset_id)
    ).all()

    result = []

    for run in runs:
        evals = session.exec(
            select(TrainingEvaluation).where(
                TrainingEvaluation.run_id == run.id
            )
        ).all()

        result.append({
            "run_id": run.id,
            "dataset_id": dataset_id,
            "evaluations": [
                {
                    "precision": e.precision or 0,
                    "recall": e.recall or 0,
                    "f1": e.f1 or 0,
                    "per_label": e.per_label or {},
                }
                for e in evals
            ]
        })

    return result