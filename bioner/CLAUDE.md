# CLAUDE.md — bioner

Biomedical Named Entity Recognition microservice. Stateless inference (`/ner`) plus a GLiNER fine-tuning
pipeline that streams events back to the backend. Served with LitServe; FastAPI adds the training routes.
See root `CLAUDE.md` for the cross-service picture.

## Stack

Python 3.10 · torch 2.8 · transformers 4.51 · gliner 0.2.x / gliner2 1.x · peft (LoRA) · bitsandbytes (4-bit) ·
litserve · fastapi · huggingface_hub. Deps in `requirements.txt`.

## Run

The service is started as a module with CLI args (compose passes these from `BIONER_*` env vars):

```bash
python -m app.main \
  --engine {gliner|huggingface} \           # required (gliner2 is WIP/disabled)
  --model  <HF id | /models/local-dir> \    # required
  --adapter_model <PEFT/LoRA path> \         # optional (huggingface engine only)
  --prompt_path <prompts.json> \             # optional (LLM engine)
  --host 0.0.0.0 --port 5600 \               # main.py defaults to 8000; compose runs 5600 (BIONER_PORT)
  --use_gpu {true|false}
```

```bash
# local dev
python -m venv .venv && . .venv/bin/activate && pip install -e .[test]
python -m app.main --engine gliner --model E3-JSI/gliner-multi-med-ner-synthetic-v1 --port 5600

# tests / lint / format
bash scripts/test.sh      # pytest + coverage
bash scripts/lint.sh      # mypy + ruff check (+ format --check)
bash scripts/format.sh    # ruff --fix + ruff format
```

## HTTP API

- `POST /ner` — `{"medical_text": "...", "labels": ["DISEASE","SYMPTOM"]}` → entities with
  `text, label, start, end, score` (char offsets, re-mapped to global positions after chunking).
- `GET /model/info` — model name/version from `metadata.json`.
- `GET /health` — health check (compose start_period is 600s to allow first-run model download).
- `POST /training/start` (202) · `GET /training/status/{run_id}` · `POST /training/stop/{run_id}`.

## Layout

- `app/main.py` — CLI parsing + LitServe/FastAPI server bootstrap.
- `app/engines/` — `build_engine()` factory + `base_engine.py` and the engines:
  `gliner_engine`, `llm_engine_huggingface` (4-bit quant + optional PEFT adapter). `gliner2_engine`
  exists but is **WIP and not wired up** (disabled in `build_engine` and the `--engine` choices).
- `app/training/` — `gliner_trainer.py` (GLiNERFinetuner: clean data, train/val split, GLiNER Trainer,
  eval), `job_manager.py` (singleton — **one active job at a time**, returns 409 on conflict),
  `callbacks.py` (`send_event` webhooks to backend).
- `app/routes_training.py` · `app/interfaces.py` (NERRequest, Entity) · `app/core/settings.py`
  (`BACKEND_HOST` for callbacks) · `app/utils/` (prompts, text_chunking, json_parser) ·
  `app/library/ner_metrics.py` · `app/tests/`.

## Models & training

- `--model` is a HF id (downloaded to `HF_HOME=/.cache`, shared with backend) or a local dir under
  `/models` (`./bioner/models` mounted rw, `BIONER_MODELS_DIR=/models`).
- Drop a local model in `bioner/models/<name>` → use `--model /models/<name>`.
- Trained models are written to `/models/run-<run_id>-<YYYYMMDD_HHMMSS>/` with a `metadata.json`; select
  one later via `--model /models/run-<id>-<ts>`.
- Training data accepted as token form `{"tokenized_text":[...], "ner":[[tok_start,tok_end,label],...]}`
  or char form `{"text":..., "ner":[[char_start,char_end,label],...]}`. Entities whose text can't be
  located are silently skipped.

## Gotchas

- GLiNER trims input to ~384 words per chunk before inference; offsets are adjusted back.
- `--use_gpu true` needed for CUDA; 4-bit LLM quantization requires a CUDA GPU. Training calls
  `torch.cuda.empty_cache()` + `gc.collect()` on cleanup.
- Backend training-event callbacks are best-effort (3s timeout, daemon threads) — failures don't stop
  training; the backend should poll `/training/status/{run_id}` for authoritative state.
