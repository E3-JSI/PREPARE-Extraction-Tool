from sqlmodel import Session, SQLModel, create_engine
from app.models_db import AppSettings


def test_app_settings_singleton_defaults_to_null_model():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        row = AppSettings(id=1, active_model_id=None)
        db.add(row)
        db.commit()
        db.refresh(row)
        assert row.id == 1
        assert row.active_model_id is None
