# app/routes/v1/settings.py

#from backend.app.core.models.embedding_base import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel


from app.core.database import get_session
from app.models_db import User, ModelArtifact
from app.routes.v1.auth import get_current_user
 
router = APIRouter(tags=["Model_settings"])


class SelectModelRequest(BaseModel):
    model_id: int

# =========================
# GET AVAILABLE MODELS
# =========================
@router.get("/models")
def get_available_models(
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    models = db.exec(select(ModelArtifact)).all()

    return [
        {
            "id": m.id,
            "name": m.name,
            "path": m.path,
            "created_at": m.created_at,
        }
        for m in models
    ]


# =========================
# GET CURRENT MODEL
# =========================
@router.get("/models/current")
def get_current_model(
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not current_user.current_model_id:
        return {"model": None}

    model = db.get(ModelArtifact, current_user.current_model_id)

    if not model:
        return {"model": None}

    return {
        "id": model.id,
        "name": model.name,
        "path": model.path,
    }


# =========================
# SET CURRENT MODEL
# =========================
@router.post("/models/select")
def select_model(
    payload: SelectModelRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    model = db.get(ModelArtifact, payload.model_id)

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    current_user.current_model_id = payload.model_id

    db.add(current_user)
    db.commit()

    return {
        "message": f"Model '{model.name}' selected"
    }