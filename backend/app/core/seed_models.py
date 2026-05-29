from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.database import engine
from app.models_db import TrainingRun

HF_MODELS = [
    {
        "name": "gliner_small",
        "path": "urchade/gliner_small",
    },
    {
        "name": "medical_gliner_v2",
        "path": "ErikCalcina/synthetic-multi-med-notes-ner-gliner_multi-v2.1",
    },
]


def seed_builtin_models():
    from app.models_db import UserModelPreference

    DEFAULT_MODEL_PATH = "urchade/gliner_small"

    with Session(engine) as session:

        for model in HF_MODELS:

            exists = session.exec(
                select(TrainingRun).where(
                    TrainingRun.output_model_path == model["path"]
                )
            ).first()

            if not exists:
                run = TrainingRun(
                    dataset_id=0,
                    status="completed",
                    base_model=model["name"],
                    labels=[],
                    output_model_path=model["path"],
                    engine="gliner",
                    created_at=datetime.now(timezone.utc),
                )
                session.add(run)
                session.flush()  # important to get ID

                print(f"🔥 Seeded model: {model['name']}")
            else:
                run = exists

        # -----------------------------------
        # ENSURE DEFAULT USER PREFERENCE EXISTS
        # -----------------------------------
        default_run = session.exec(
            select(TrainingRun).where(
                TrainingRun.output_model_path == DEFAULT_MODEL_PATH
            )
        ).first()

        if default_run:
            # create system-wide default user (or admin user = 1)
            pref = session.exec(
                select(UserModelPreference)
                .where(UserModelPreference.user_id == 1)
            ).first()

            if not pref:
                session.add(
                    UserModelPreference(
                        user_id=1,
                        model_id=default_run.id,
                    )
                )

                print("✅ Default user model preference set")

        session.commit()

        print("✅ Built-in model seeding complete")