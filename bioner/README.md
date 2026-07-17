# bioner

Lightweight API service to extract named entities from medical text, plus a GLiNER fine-tuning pipeline.
Provides two engines:

- **GLiNER engine**: `app.engines.gliner_engine.GlinerEngine` (fast deterministic NER).
- **LLM engine**: `app.engines.llm_engine_huggingface.LLMEngineHuggingFace` (local Hugging Face models,
  4-bit quantized, optional PEFT/LoRA adapters).

## ☑️ Requirements

Before starting make sure these are available:

- python (version >= 3.10)
- git
- (required for the LLM engine) CUDA drivers and a GPU — 4-bit quantization needs CUDA
- (optional) docker and docker compose for containerized runs

## 🛠️ Setup

### Create a python environment

```bash
# from the bioner folder
python -m venv .venv

# activate (UNIX)
source .venv/bin/activate

# deactivate
deactivate
```

### Install the requirements

```bash
pip install -e .[test]     # runtime + test deps
pip install -e .[all]      # everything (dev tooling included)
```

## 🧪 Development

Start the server by running the main module. It launches a LitServe instance (FastAPI mounted for the
training routes).

Example (GLiNER engine):

```bash
python -m app.main --engine gliner --model E3-JSI/gliner-multi-med-ner-synthetic-v1 --port 5600
```

Example (LLM engine):

```bash
python -m app.main \
  --engine huggingface \
  --model <hf-model-id> \
  --prompt_path /full/path/to/prompts.json \
  --adapter_model /full/path/to/adapter \
  --use_gpu true \
  --port 5600
```

`--model` accepts a Hugging Face id (downloaded to `HF_HOME`) or a local directory (in Docker: a
subdirectory of `/models`, mounted from `./bioner/models`). `--engine` choices: `gliner`, `huggingface`.

The server defaults to port 8000; the compose stack runs it on `BIONER_PORT` (default 5600). Test with curl:

```bash
curl -sS -X POST http://localhost:5600/ner \
  -H "Content-Type: application/json" \
  -d '{"medical_text":"Patient has fever and cough.","labels":["DISEASE","SYMPTOM"]}'
```

### HTTP API

| Endpoint | Description |
| --- | --- |
| `POST /ner` | Extract entities: `{"medical_text": "...", "labels": [...]}` → `text, label, start, end, score` |
| `GET /model/info` | Model name/version from `metadata.json` |
| `GET /health` | Health check |
| `POST /training/start` | Start a GLiNER fine-tuning run (202; one active job at a time, 409 on conflict) |
| `GET /training/status/{run_id}` | Authoritative training state |
| `POST /training/stop/{run_id}` | Stop a running training job |

Trained models are written to `models/run-<run_id>-<timestamp>/` and can be served later via
`--model /models/run-<run_id>-<timestamp>`.

### Tests, lint, format

```bash
bash scripts/test.sh      # pytest + coverage
bash scripts/lint.sh      # mypy + ruff check (+ format --check)
bash scripts/format.sh    # ruff --fix + ruff format
```

## 🐳 Docker

The service is part of the root `docker-compose.yaml` (service name `bioner`), which passes the CLI args
from the `BIONER_*` variables in the root `.env` and mounts `./bioner/models` → `/models` plus the shared
HuggingFace cache `./.cache` → `/.cache`:

```bash
# from the repository root
docker compose up -d bioner
```

To build and run the image standalone:

```bash
docker build -t bioner .

docker run -d -p 5600:5600 --name bioner \
  -v "$(pwd)/models:/models" \
  bioner python -m app.main --engine gliner --model <hf-id-or-/models/dir> --port 5600
```
