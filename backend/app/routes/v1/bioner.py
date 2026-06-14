import os

import requests
from datetime import datetime, timezone
from typing import List
import time
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import Session, select
from sqlalchemy import func 

import requests
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.settings import settings
from app.models_db import Record, SourceTerm, TrainingRun
from app.routes.v1.auth import get_current_user
from app.schemas import GLiNERTrainingRequest
from app.services.gliner_data_service import build_gliner_training_data, load_reviewed_training_data

HF_MODELS = [
    {
        "name": "gliner_small",
        "path": settings.BIONER_DEFAULT_MODEL,
    },
    {
        "name": "medical_gliner_v2",
        "path": settings.BIONER_DEFAULT_MODEL_PVT,
    },
    ]


router = APIRouter(tags=["BioNER"])

from app.core.database import Dataset, User, engine, get_session
from app.core.settings import settings
from app.interfaces import Entity, LabelsInput, NERRequest
from app.library.record_processing import link_dates_for_record
from app.models_db import (
    ExtractionJob,
    Record,
    SourceTerm,
    TrainingRun,
    TrainingEvaluation,
)
from app.routes.v1.auth import get_current_user
from app.schemas import (
    ExtractionJobStartResponse,
    ExtractionJobStatusResponse,
    MessageOutput,
)

from datetime import datetime, timezone
from app.models_db import UserModelPreference, ModelArtifact
from fastapi import APIRouter, Depends
from sqlmodel import Session
from app.core.database import get_session 

router = APIRouter(tags=["BioNER"])


# =========================================================
# ENTITY EXTRACTION
# =========================================================

@router.post("/extract", response_model=List[Entity])
def extract_entities(
    request: NERRequest,
):
    """
    Extract named entities from medical text using the BioNER service.
    """

    try:
        response = requests.post(
            f"{settings.EXTRACT_HOST}/ner",
            json=request.dict(),
            timeout=300,
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Extract service unavailable",
        )


# =========================================================
# SINGLE RECORD EXTRACTION
# =========================================================

@router.post(
    "/{dataset_id}/records/{record_id}/extract",
    response_model=MessageOutput,
)
def extract_entities_from_record(
    dataset_id: int,
    record_id: int,
    labels: LabelsInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):

    dataset = db.get(Dataset, dataset_id)

    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    if dataset.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this dataset",
        )

    statement = (
        select(Record)
        .where(Record.id == record_id)
        .where(Record.dataset_id == dataset_id)
    )

    record = db.exec(statement).one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found in this dataset",
        )

    if record.reviewed:
        return MessageOutput(
            message=f"Record {record_id} is reviewed; extraction skipped"
        )
    
    pref = db.exec(
        select(UserModelPreference)
        .where(UserModelPreference.user_id == current_user.id)
    ).first()

    # -------------------------------------------------
    # No selected model yet -> use first available one
    # -------------------------------------------------
    if not pref:

        model_obj = db.exec(
            select(TrainingRun)
            .where(TrainingRun.output_model_path != None)
        ).first()

        if not model_obj:
            raise HTTPException(
                status_code=404,
                detail="No models available"
            )

        # create default preference automatically
        pref = UserModelPreference(
            user_id=current_user.id,
            model_id=model_obj.id,
        )

        db.add(pref)
        db.commit()
        db.refresh(pref)

    else:
        model_obj = db.get(TrainingRun, pref.model_id)

    # -------------------------------------------------
    # Final model config
    # -------------------------------------------------
    engine_name = getattr(model_obj, "engine", "gliner")
    model_path = model_obj.output_model_path
    
    print("\n================ NER MODEL DEBUG ================")
    print(f"User ID      : {current_user.id}")
    print(f"Engine       : {engine_name}")
    print(f"Model Path   : {model_path}")
    print("=================================================\n")

    request_data = {
        "medical_text": record.text,
        "labels": labels.labels,
        "engine": engine_name,
        "model": model_path,
    }

    print("\n--------------- REQUEST TO /NER ---------------")
    print(request_data)
    print("------------------------------------------------\n")

    try:
        response = requests.post(
            f"{settings.EXTRACT_HOST}/ner",
            json=request_data,
            timeout=300,
        )

        response.raise_for_status()

        entities = response.json()

    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Extraction service unavailable",
        )

    existing_keys = {
        (t.value, t.label, t.start_position, t.end_position)
        for t in db.exec(
            select(SourceTerm)
            .where(SourceTerm.record_id == record_id)
        ).all()
    }

    new_terms: List[SourceTerm] = []

    for entity in entities:

        key = (
            entity["text"],
            entity["label"],
            entity["start"],
            entity["end"],
        )

        if key in existing_keys:
            continue

        existing_keys.add(key)

        new_terms.append(
            SourceTerm(
                record_id=record_id,
                value=entity["text"],
                label=entity["label"],
                start_position=entity["start"],
                end_position=entity["end"],
                score=entity.get("score"),
                automatically_extracted=True,
            )
        )

    if new_terms:
        db.add_all(new_terms)
        db.flush()

        link_dates_for_record(db, record, dataset)

        db.commit()

    return MessageOutput(
        message=f"Extracted and saved {len(new_terms)} entities from record {record_id}"
    )


# =========================================================
# DATASET EXTRACTION
# =========================================================

@router.post(
    "/{dataset_id}/records/extract",
    response_model=ExtractionJobStartResponse,
)
def extract_entities_from_records(
    dataset_id: int,
    labels: LabelsInput,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):

    dataset = db.get(Dataset, dataset_id)

    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    if dataset.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this dataset",
        )

    records = db.exec(
        select(Record)
        .where(Record.dataset_id == dataset_id)
    ).all()

    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No records found for this dataset",
        )

    records_to_process = [r for r in records if not r.reviewed]
    total = len(records_to_process)
    job = ExtractionJob(
        dataset_id=dataset_id,
        total=total,
        completed=0,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if total == 0:
        job.status = "completed"
        job.updated_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()

        return ExtractionJobStartResponse(
            job_id=job.id,
            dataset_id=dataset_id,
            total=total,
            status=job.status,
        )
    pref = db.exec(
            select(UserModelPreference)
            .where(UserModelPreference.user_id == current_user.id)
        ).first()
    if not pref:
        # fallback: pick seeded default model
        default_model = db.exec(
            select(TrainingRun)
            .where(TrainingRun.output_model_path == settings.BIONER_DEFAULT_MODEL)
        ).first()

        if not default_model:
            raise HTTPException(500, "No default model available")

        pref = UserModelPreference(
            user_id=current_user.id,
            model_id=default_model.id,
        )
        db.add(pref)
        db.commit()
        db.refresh(pref)

    model_obj = db.get(TrainingRun, pref.model_id)

    engine_name = model_obj.engine if hasattr(model_obj, "engine") else "gliner"
    model_path = model_obj.output_model_path

    background_tasks.add_task(
        run_dataset_extraction_job,
        job_id=job.id,
        dataset_id=dataset_id, 
        labels=labels.labels,
        engine_name=engine_name,
        model_path=model_path,
        )

    return ExtractionJobStartResponse(
        job_id=job.id,
        dataset_id=dataset_id,
        total=total,
        status=job.status,
    )


@router.get(
    "/{dataset_id}/records/extract/{job_id}/status",
    response_model=ExtractionJobStatusResponse,
)
def get_extraction_job_status(
    dataset_id: int,
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):

    dataset = db.get(Dataset, dataset_id)

    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    if dataset.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this dataset",
        )

    job = db.get(ExtractionJob, job_id)

    if job is None or job.dataset_id != dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction job not found for this dataset",
        )

    return ExtractionJobStatusResponse(
        job_id=job.id,
        dataset_id=job.dataset_id,
        total=job.total,
        completed=job.completed,
        status=job.status,
        error_message=job.error_message,
    )


# =========================================================
# TRAINING
# =========================================================

@router.post("/training/start")
def start_training(
    request: GLiNERTrainingRequest,
    db: Session = Depends(get_session),
    user=Depends(get_current_user),
):

    # 🔥 PRINT BASE MODEL
    print("\n🚀 TRAINING START REQUEST")
    print("Dataset ID:", request.dataset_id)
    print("Labels:", request.labels)
    print("Base Model:", request.base_model)
    print("Epochs:", request.num_epochs)
    print("Learning Rate:", request.learning_rate)
    print("Batch Size:", request.train_batch_size)
    print("Device:", request.device)
    print("Validation Ratio:", request.val_ratio)
    print("=" * 50)

    # ⏸️ DELAY 20 SECONDS (debug only)
    #time.sleep(20)

    training_data = load_reviewed_training_data(db, request.dataset_id, request.labels)
    print(training_data)
    #training_data = build_gliner_training_data(records, terms)

    #training_data = tokenize(records, terms)

        # Save to JSON
    output_dir = Path("training_data")
    output_dir.mkdir(exist_ok=True)

    json_path = output_dir / f"dataset_{request.dataset_id}_gliner.json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(training_data, f, ensure_ascii=False, indent=2)

    print(f"✅ Training data saved: {json_path}")
    print(f"Samples: {len(training_data)}")


    if not training_data:
        raise HTTPException(400, "No training data")

    run = TrainingRun(
        dataset_id=request.dataset_id,
        status="running",
        base_model=request.base_model,
        labels=request.labels,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # send ONLY to Bioner
    try:
        resp = requests.post(
            f"{settings.EXTRACT_HOST}/training/start",
            json={
                "run_id": run.id,
                "base_model": request.base_model,
                "training_data": training_data,
                "num_epochs": request.num_epochs,
                "learning_rate": request.learning_rate,
                "train_batch_size": request.train_batch_size,
                "device": request.device,
                "val_ratio": request.val_ratio,
            },
            timeout=30,
        )
        resp.raise_for_status()

    except Exception as e:
        run.status = "failed"
        db.add(run)
        db.commit()
        raise HTTPException(503, str(e))

    return {"run_id": run.id, "status": "running"}

@router.post("/training/stop/{run_id}")
def stop_training(run_id: int):
    try:
        resp = requests.post(f"{settings.EXTRACT_HOST}/training/stop/{run_id}")
        return resp.json()
    except Exception:
        raise HTTPException(503, "Bioner unavailable")


@router.get("/training/status/{run_id}")
def training_status(run_id: int):
    try:
        resp = requests.get(f"{settings.EXTRACT_HOST}/training/status/{run_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        raise HTTPException(503, "Bioner unavailable")


# =========================
# STOP TRAINING
# =========================


# =========================================================
# MONITORING
# =========================================================

@router.get("/datasets/{dataset_id}/full-stats")
def get_full_stats(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):

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
            label: count
            for label, count in label_distribution
        },
    }


@router.get("/datasets/{dataset_id}/runs")
def get_runs_for_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):

    runs = db.exec(
        select(TrainingRun)
        .where(
            TrainingRun.dataset_id == dataset_id,
            TrainingRun.status == "completed"   # ✅ ONLY COMPLETED RUNS
        )
        .order_by(TrainingRun.id.desc())
    ).all()

    return [
        {
            "run_id": run.id,
            "dataset_id": run.dataset_id,
            "status": run.status,
        }
        for run in runs
    ]


@router.get("/runs/{run_id}/evaluation")
def get_run_evaluation(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):

    evaluation = db.exec(
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


@router.get("/evaluations")
def get_all_evaluations(db: Session = Depends(get_session)):
    rows = db.exec(
        select(TrainingEvaluation, TrainingRun)
        .join(TrainingRun, TrainingRun.id == TrainingEvaluation.run_id)
    ).all()
    return [
        {
            "run_id": ev.run_id,
            "dataset_id": run.dataset_id,
            "precision": ev.precision,
            "recall": ev.recall,
            "f1": ev.f1,
            "per_label": ev.per_label,
        }
        for ev, run in rows
    ]

@router.get("/datasets/{dataset_id}/runs/evaluations")
def get_dataset_runs_evaluations(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):

    runs = db.exec(
        select(TrainingRun)
        .where(TrainingRun.dataset_id == dataset_id)
    ).all()

    result = []

    for run in runs:

        evals = db.exec(
            select(TrainingEvaluation)
            .where(TrainingEvaluation.run_id == run.id)
        ).all()

        evaluations = [
            {
                "precision": e.precision or 0,
                "recall": e.recall or 0,
                "f1": e.f1 or 0,
                "per_label": e.per_label or {},
            }
            for e in evals
        ]

        # ✅ FILTER OUT RUN IF ALL METRICS ARE ZERO
        has_valid_score = any(
            ev["precision"] != 0 or ev["recall"] != 0 or ev["f1"] != 0
            for ev in evaluations
        )

        if not has_valid_score:
            continue  # ❌ skip this run completely

        result.append({
            "run_id": run.id,
            "dataset_id": dataset_id,
            "evaluations": evaluations,
        })

    return result
# =========================================================
# MODEL MANAGEMENT
# =========================================================

@router.post("/models/select")
def select_model(
    request: dict,
    db: Session = Depends(get_session),
    user=Depends(get_current_user),
):
    user_id = user.id

    model_id = request["model_id"]

    model_obj = db.get(TrainingRun, model_id)
    if not model_obj:
        raise HTTPException(404, "Model not found")

    print("REQUEST BODY:", request)
    # 1. Save preference (THIS is the important part)
    pref = db.exec(
        select(UserModelPreference).where(UserModelPreference.user_id == user_id)
    ).first()

    if pref:
        pref.model_id = model_id
        pref.updated_at = datetime.now(timezone.utc)
    else:
        pref = UserModelPreference(
            user_id=user_id,
            model_id=model_id,
        )
        db.add(pref)

    db.commit()

    # 2. Tell inference service to switch model
    """requests.post(
        f"{settings.EXTRACT_HOST}/models/switch",
        json={
            "engine": model_obj.engine or "gliner",
            "model": model_obj.model_path,
        },
        timeout=10,
    )"""

    print(f"Switched model: {model_id}")
    return {
        "status": "ok",
        "model_id": model_id,
        "model_path": model_obj.output_model_path,
    }


@router.post("/models/switch")
def switch_model_endpoint(request: dict, db: Session = Depends(get_session),):
    user_id = request["user_id"]
    return switch_user_model(request, db, user_id)

@router.get("/models/current")
def get_current_model():
    try:
        response = requests.get(
            f"{settings.EXTRACT_HOST}/models/current",
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BioNER service unavailable",
        )


@router.get("/models/health")
def check_model_health():

    try:

        response = requests.get(
            f"{settings.EXTRACT_HOST}/models/health",
            timeout=10,
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException:

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BioNER service unavailable",
        )


@router.get("/models/available")
def list_available_models(db: Session = Depends(get_session)):
    models = []

    for hf_model in HF_MODELS:
        models.append({
            "id": None,
            "name": hf_model["name"],
            "engine": "gliner",
            "path": hf_model["path"],
            "type": "huggingface",
            "created_at": None,
        })


    # 2. DB-trained models
    runs = db.exec(
        select(TrainingRun).where(TrainingRun.output_model_path != None)
    ).all()

    for run in runs:
        #if run.output_model_path and os.path.exists(run.output_model_path):
        if run.output_model_path and run.status == "completed":
            models.append({
                "id": run.id,
                "name": os.path.basename(run.output_model_path),
                "engine": "gliner",
                "path": run.output_model_path,
                "type": "local",
                "created_at": run.created_at.isoformat() if run.created_at else None,
            })

    return {
        "models": models,
        "selected_model": None  # or fetch current model if you want
    }

def switch_user_model(request, db, user_id: int):
    # -------------------------
    # Extract model_id safely
    # -------------------------
    model_id = request.get("model_id") if isinstance(request, dict) else request.model_id
    # -------------------------
    # Validate model exists
    # -------------------------
    model_obj = db.get(TrainingRun, model_id)
    if not model_obj:
        raise ValueError("Model not found in DB")
    # -------------------------
    # Upsert user preference
    # -------------------------
    pref = (
        db.query(UserModelPreference)
        .filter(UserModelPreference.user_id == user_id)
        .first()
    )
    if pref:
        pref.model_id = model_obj.id
        pref.updated_at = datetime.now(timezone.utc)
    else:
        pref = UserModelPreference(
            user_id=user_id,
            model_id=model_obj.id,
        )
        db.add(pref)

    db.commit()

    print(f"Switched model: {model_id}")
    return {
        "status": "ok",
        "model_id": model_obj.id,
        "model_path": model_obj.output_model_path,
    }

def run_dataset_extraction_job(job_id: int, dataset_id: int, labels: List[str],engine_name: str,
    model_path: str,):
    """Background task that extracts entities for each unreviewed record."""

    with Session(engine) as session:
        job = session.get(ExtractionJob, job_id)
        if job is None:
            return

        dataset = session.get(Dataset, dataset_id)

        if job.status == "cancelled":
            return

        job.status = "running"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

        records = session.exec(
            select(Record).where(Record.dataset_id == dataset_id)
        ).all()

    
        print("\n================ NER MODEL DEBUG ================") 
        print(f"Engine       : {engine_name}")
        print(f"Model Path   : {model_path}")
        print("=================================================\n")

        # Skip reviewed records and records already containing automatically extracted terms
        unreviewed_records = [r for r in records if not r.reviewed]
        processed_records = []
        records_to_process: List[Record] = []

        print("TOTAL RECORDS:", len(records))
        print("UNREVIEWED:", len(unreviewed_records))
        print("TO PROCESS:", len(records_to_process))

        for record in unreviewed_records:
            has_auto = session.exec(
                select(SourceTerm.id)
                .where(SourceTerm.record_id == record.id)
                .where(SourceTerm.automatically_extracted == True)  # noqa: E712
            ).first()

            if has_auto:
                processed_records.append(record)
            else:
                records_to_process.append(record)

        job.total = len(unreviewed_records)
        job.completed = len(processed_records)
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

        for record in records_to_process:
            session.refresh(job)
            if job.status == "cancelled":
                job.updated_at = datetime.now(timezone.utc)
                session.add(job)
                session.commit()
                return

            request_data = {
                        "medical_text": record.text,
                        "labels": labels,
                        "engine": engine_name,
                        "model": model_path,
                    }

            print("\n--------------- REQUEST TO /NER 2 ---------------")
            print(request_data)
            print("------------------------------------------------\n")
            print("\n🧠 NER CONFIG")
            print(f"Engine: {engine_name}")
            print(f"Model Path: {model_path}")
            print(f"EXTRACT_HOST: {settings.EXTRACT_HOST}")
            print("TOTAL RECORDS:", len(records))
            print("UNREVIEWED:", len(unreviewed_records))
            print("TO PROCESS:", len(records_to_process))


            try:
                response = requests.post(
                    f"{settings.EXTRACT_HOST}/ner", json=request_data, timeout=300
                )
                response.raise_for_status()
                entities = response.json()
            except requests.RequestException as exc:
                job.status = "failed"
                job.error_message = str(exc)
                job.updated_at = datetime.now(timezone.utc)
                session.add(job)
                session.commit()
                return

            existing_keys = {
                (t.value, t.label, t.start_position, t.end_position)
                for t in session.exec(
                    select(SourceTerm).where(SourceTerm.record_id == record.id)
                ).all()
            }

            new_terms: List[SourceTerm] = []
            for entity in entities:
                key = (
                    entity["text"],
                    entity["label"],
                    entity["start"],
                    entity["end"],
                )
                if key in existing_keys:
                    continue

                existing_keys.add(key)
                new_terms.append(
                    SourceTerm(
                        record_id=record.id,
                        value=entity["text"],
                        label=entity["label"],
                        start_position=entity["start"],
                        end_position=entity["end"],
                        score=entity.get("score"),
                        automatically_extracted=True,
                    )
                )

            if new_terms:
                session.add_all(new_terms)
                session.flush()
                link_dates_for_record(session, record, dataset)

            job.completed += 1
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()

        job.status = "completed"
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()