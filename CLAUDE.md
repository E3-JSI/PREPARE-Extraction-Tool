# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PREPARE Extraction Tool maps codes from coding systems to OHDSI Vocabulary standard concepts.
It extracts medical terms from unstructured text and maps them to OHDSI vocabularies (Athena).
Adaptation/extension of the OHDSI Usagi tool.

## Architecture — three services + two data stores

```
frontend (React/Vite :3000)  ──/api──▶  backend (FastAPI :8000)  ──HTTP──▶  bioner (NER :5600)
                                              │  │                              ▲
                                              │  └── PostgreSQL :5432           │ training-event callbacks
                                              └───── Elasticsearch :9200        ┘
```

- **backend** — FastAPI API. Owns Postgres (datasets, terms, mappings, training runs) and Elasticsearch
  (concept indexing + semantic search via embeddings). Orchestrates extraction and training by calling bioner.
- **bioner** — Biomedical NER microservice (GLiNER / LLM engines). Stateless inference + a fine-tuning
  pipeline that streams training events back to the backend.
- **frontend** — React 19 SPA for the extract → cluster → map workflow.

Each service has its own `CLAUDE.md` (`backend/`, `bioner/`, `frontend/`) with detailed commands and layout.

## The core domain workflow

1. **Upload dataset** of records (unstructured medical text).
2. **Extract** source terms via bioner NER (`backend → bioner /ner`).
3. **Cluster** semantically-similar source terms (embedding similarity; drag-drop UI).
4. **Map** clusters/terms to OHDSI standard concepts (Elasticsearch semantic search over indexed vocabularies).
5. Optionally **train** a custom GLiNER model from annotated data (backend creates a run, bioner trains,
   events stream back, trained model saved to `bioner/models/run-<id>-<timestamp>/`).

## Running the full stack

```bash
cp .env.example .env                                   # then edit (SECRET_KEY etc.)
# place GLiNER model: extract model.zip into bioner/models/  (or set BIONER_MODEL to a HF id)
docker-compose up -d
docker compose exec backend alembic upgrade head       # migrations (required)
./scripts/seed.sh                                       # optional: load vocabularies into PG + ES
```

- Frontend http://localhost:3000 · API docs http://localhost:8000/docs · Adminer http://localhost:8080

## Config — single source of truth

- One root `.env` (from `.env.example`) is shared by all services via `env_file` in compose.
- **Service-to-service hosts default to `localhost`** (for running services directly on the host).
  docker-compose **overrides** the cross-service ones with compose service names automatically:
  `EXTRACT_HOST=http://bioner:5600`, `BACKEND_HOST=http://backend:8000`. Do not hardcode hosts —
  read them from settings/env.
- `./.cache` is the shared HuggingFace cache (`HF_HOME`) mounted into both backend and bioner so model
  downloads persist and aren't duplicated.

## Conventions

- Python services: Python 3.10+, `ruff` for lint/format, `pytest`. Config in each service's `pyproject.toml`.
- YAML/TOML preferred over JSON for config.
- Postgres is authoritative for app data; Elasticsearch is a derived search index (one index per vocabulary).
