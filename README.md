<p align="center">
  <img src="frontend/src/assets/images/logo.svg" alt="PREPARE Extraction Tool" width="400"/>
</p>

PREPARE Extraction Tool is an application to help create mappings between coding systems and the Vocabulary standard concepts.
The tool is an adaptation/extension of the OHDSI Usagi tool, focusing on extracting relevant medical terms
from unstructured text and mapping them to the OHDSI vocabularies available on OHDSI Athena.

## Running the Tool

### Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for local frontend development)
- Python 3.10+ (for local backend development)

### Using Docker (Recommended)

This is the easiest way to run the full stack. Open a terminal in the project root and follow the steps below.

#### First Time Setup

1. **Clone the repository:**

    ```bash
    git clone <repository-url>
    cd PREPARE-Extraction-Tool
    ```

2. **Set up environment variables:**

    ```bash
    cp .env.example .env
    # Edit .env with your configuration
    ```

    Key host configuration variables:

    | Variable | Default | Description |
    |----------|---------|-------------|
    | `FRONTEND_HOST` | `http://localhost:3000` | URL where the frontend is accessible |
    | `BACKEND_HOST` | `http://localhost:8000` | URL where the backend API is accessible |
    | `EXTRACT_HOST` | `http://localhost:5600` | URL where the extraction service is accessible |

3. **Place the GLiNER model files:**

    Use the shared zip file named `model.zip`, extract it, and place the extracted `model` folder inside `bioner`.
    If you have a fine-tuned model, place that extracted model folder in the same location.

    Expected result:

    ```text
    bioner/model/
    ```

4. **Start all services:**

    ```bash
    docker-compose up -d
    ```
    
5. **Apply database migrations:**

    ```bash
    docker compose exec backend alembic upgrade head
    ```

6. **(Optional) Load Medical Vocabularies:**
   
    This step populates PostgreSQL and Elasticsearch with the main medical vocabularies and concepts required for mapping.
    
    * **Note:** You can skip this step now and manually upload these vocabularies through the application interface later.
    * **Prerequisite:** Ensure the required data files (`vocabulary.csv`, `concept.csv`, and the `es_repo` folder) are placed inside the `seed_data` directory.
    * **Run the script:**
    ```bash
    ./scripts/seed.sh
    ```

7. **Access the application** by opening http://localhost:3000 in your browser (using default host values):

    - Frontend: http://localhost:3000 (configured via `FRONTEND_HOST`)
    - Backend API: http://localhost:8000 (configured via `BACKEND_HOST`)
    - API Documentation: http://localhost:8000/docs
    - Database Admin: http://localhost:8080

#### Every Time After That

If your containers are still running (e.g. you haven't restarted your computer), just open http://localhost:3000 in your browser — nothing else needed.

If you restarted your computer or stopped Docker, simply run:
```bash
docker-compose up -d
```
Then open http://localhost:3000.

## Label Linking

Label linking connects two extracted terms that belong together — for example a `diagnosis` and the `medicine` prescribed for it.

**Label relations** are directed "has value" pairs between label types (e.g. `diagnosis → medicine`). They are defined once, when you upload a dataset, in the dataset upload screen. Linking is only available for datasets that have at least one relation defined.

**Automatic linking** happens during extraction. It is a rule-based step that runs when relations are defined: a link is created between two extracted terms only when all of the following hold:

- Their labels match a defined relation, in that relation's direction (the `from` label appears before the `to` label in the text).
- The two terms are immediately adjacent — nothing else is extracted between them.
- Both terms fall in the same sentence.

Automatic linking is **independent of the NER model**. It depends only on the labels and positions of the extracted terms, so training or selecting a custom model does **not** add, change, or enable linking — a fine-tuned model links exactly the same way the default one does.

If an expected link does not appear, it is usually one of these reasons:

- No label relation is defined for that pair of labels.
- The two terms are not immediately adjacent (another term sits between them).
- The two terms are in different sentences.
- The terms appear in the opposite order from the relation's direction.
- Extraction was re-run on records that were already extracted — auto-linking only runs on newly extracted terms, so re-extracting produces nothing new to link.

**Manual linking** is always available once relations are defined. In the annotation panel, press `L` (or click the **Link** button), then click the two terms in the text to link or unlink them.

## Project Structure

```text
PREPARE-Extraction-Tool/
├── backend/               # FastAPI backend service
│   ├── app/               # Main application code
│   │   ├── core/          # Core configuration and utilities
│   │   ├── routes/        # API endpoints
│   │   ├── models.py      # Data models
│   │   ├── utils/         # Utility functions
│   │   └── tests/         # Backend tests
│   ├── requirements.txt   # Python dependencies
│   ├── pyproject.toml     # Project configuration
│   └── Dockerfile         # Backend container
├── frontend/              # React frontend application
│   ├── src/               # Source code
│   │   ├── components/    # React components
│   │   ├── pages/         # Page components
│   │   ├── hooks/         # Custom React hooks
│   │   └── assets/        # Static assets
│   ├── package.json       # Node.js dependencies
│   └── Dockerfile         # Frontend container
├── scripts/               # Build and deployment scripts
├── docker-compose.yaml    # Multi-container setup
└── .env                   # Environment variables (create from .env.example)
```

## Backend

The backend is built with **Python 3.10+** using the following main technologies:

- **FastAPI**: Modern, fast web framework for building APIs
- **Uvicorn**: ASGI server for running FastAPI applications
- **SQLModel**: SQL database integration with Pydantic models
- **Pydantic**: Data validation and settings management
- **PostgreSQL**: Primary database (via Docker)

## Frontend

The frontend is built with **TypeScript** and **React 19** using:

- **React 19**: Latest React with concurrent features
- **TypeScript**: Type-safe JavaScript
- **Vite**: Fast build tool and dev server
- **Storybook**: Component development and documentation
- **Vitest**: Unit testing framework
- **ESLint + Prettier**: Code quality and formatting
