# CLAUDE.md — backend

FastAPI service. Owns PostgreSQL (app data) and Elasticsearch (concept search). Orchestrates the
bioner NER/training service over HTTP. See root `CLAUDE.md` for the cross-service picture.

## Stack

Python 3.10–3.13 · FastAPI · SQLModel (SQLAlchemy + Pydantic) · pydantic-settings · PostgreSQL (psycopg2) ·
Elasticsearch 8.x · sentence-transformers / model2vec (embeddings) · Alembic · JWT auth (pyjwt + pwdlib argon2) ·
scikit-learn / hdbscan (clustering). Deps pinned in `requirements.txt` (pyproject reads them dynamically).

## Commands

```bash
# setup (local, non-docker)
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && pip install -e .[test]   # add ,dev for git hooks

# run (needs Postgres + Elasticsearch reachable; set .env at repo root)
fastapi dev app/main.py --port 8000        # auto-reload
fastapi run app/main.py --port 8000        # no reload
# or: uvicorn app.main:app --port 8000

# tests
pytest                                      # all (in-memory SQLite, no PG/ES needed)
pytest app/tests/test_datasets.py          # one file
pytest app/tests/test_login.py::test_register_user_success   # one test
pytest --cov=app

# lint / format
ruff check app/ && ruff format app/
ruff check --fix app/

# migrations (helpers in scripts/, or alembic directly)
alembic upgrade head
alembic revision --autogenerate -m "msg"
./scripts/alembic_upgrade.sh head
```

## Layout & request flow

- `app/main.py` — app factory, lifespan (checks migration status, registers embedding models, pings ES),
  exception handlers (SQLAlchemy / Elasticsearch / validation → meaningful HTTP codes, 503 if PG/ES down),
  CORS + security-headers middleware. All routes mounted under `/api/v1`.
- `app/core/` — `settings.py` (pydantic-settings, loaded from repo-root `.env`), `database.py` (engine,
  `get_session` DI, alembic config), `elastic.py` (ES client singleton), `model_registry.py` + `models/`
  (embedding models: sentence-transformer, model2vec).
- `app/routes/v1/` — one module per domain: `auth`, `datasets`, `source_term`, `clusters`, `bioner`,
  `training_events`, `vocabularies`, `mappings`, `health`.
- `app/services/` — external/IO orchestration: `bioner_client.py` (HTTP to bioner: start/stop training),
  `training_service.py` (run lifecycle + metrics), `gliner_data_service.py`, `evaluation_service.py`,
  `websocket_manager.py`.
- `app/library/` — domain logic: `concept_indexer.py` (ES index + semantic search), `record_processing.py`
  (auto-link entities/dates), `omop_export.py`, `file_parser.py`, `ner_metrics.py`.
- `app/models_db.py` — SQLModel tables · `app/schemas.py` — request/response models · `app/tests/` (conftest fixtures).

## Key integrations

- **bioner**: `POST {EXTRACT_HOST}/ner` for extraction; `/training/start` + `/training/stop/{run_id}` for
  training. bioner posts progress back to `/api/v1/bioner/...` training-event endpoints (poll/websocket for state).
- **Elasticsearch**: one index per vocabulary; concepts stored with sentence embeddings; semantic search
  drives auto-linking source terms → standard concepts.

## Gotchas

- Settings validate `DATABASE_URL` must be PostgreSQL and `ELASTICSEARCH_URL` must be http(s). `BACKEND_CORS_ORIGINS`
  accepts comma-separated or JSON array.
- Tests set env vars in `conftest.py` **before** importing `app` modules — keep that ordering. ES is not
  fixtured; tests touching `es_client` must mock it.
- ruff post-migration hook in `alembic.ini` is commented out (not active).
