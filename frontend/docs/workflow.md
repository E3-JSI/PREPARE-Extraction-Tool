# The Workflow

The frontend exists to drive one domain workflow: **upload → extract → cluster → map**,
with optional **model training/monitoring**. This doc walks the pages in order and how
data flows between them. Page code is in `src/pages/`; routing is in
[background/routing-and-auth.md](./background/routing-and-auth.md).

## The pipeline

```
Datasets ──▶ DatasetUpload ──▶ DatasetOverview
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
DatasetTermExtraction ──▶ DatasetTermClustering ──▶ DatasetConceptMapping
   (extract source terms)     (group similar terms)     (map to OHDSI concepts)
```

Each dataset moves left-to-right; the URL carries the `:datasetId` through every step
(`/datasets/:datasetId/records | /clusters | /mapping`).

## Steps

### 1. Datasets & upload

- **`Datasets`** (`/datasets`) — list datasets, create/delete, entry point.
- **`DatasetUpload`** (`/datasets/upload`) — upload a file of unstructured medical-text
  records. Uses `XMLHttpRequest` with an upload-progress bar and a 10-minute timeout
  (see [background/api-layer.md](./background/api-layer.md#file-uploads)).
- **`DatasetOverview`** (`/datasets/:datasetId`) — dataset summary, labels, and stats;
  the hub you branch into the three workflow steps from.

### 2. Extraction — `DatasetTermExtraction`

Route `/datasets/:datasetId/records`. Runs biomedical NER over records to produce
**source terms**, driven by `useExtractionPolling`
([background/state-and-hooks.md](./background/state-and-hooks.md#useextractionpolling)):

- Extract a **single record** (immediate) or the **whole dataset** (background job).
- Dataset jobs poll status every 2 s with a progress bar; the `job_id` is persisted in
  `localStorage` so the job **resumes** if you reload or navigate away and back.
- Requires the dataset to have **labels** defined — extraction targets those entity
  types. Labels get deterministic colors via `getLabelColorClass`
  (see [components.md](./components.md#label-category-colors)).

### 3. Clustering — `DatasetTermClustering`

Route `/datasets/:datasetId/clusters`. Group semantically-similar source terms into
clusters via a **drag-and-drop** UI built on `@dnd-kit`:

- Components: `ClusterCard`, `ClusterOverlay`, `DraggableTerm`,
  `DroppableUnclusteredArea`, `TermOverlay`.
- The backend seeds clusters by embedding similarity; the user refines membership by
  dragging terms between clusters and the unclustered pool.
- Membership changes persist through the `clusters` API module.

### 4. Mapping — `DatasetConceptMapping`

Route `/datasets/:datasetId/mapping`. Map clusters/terms to **OHDSI standard concepts**:

- Semantic search over indexed vocabularies (backed by Elasticsearch on the backend) via
  the `mappings` API module.
- Assign the chosen standard concept to a cluster/term; the mapping is the workflow's
  output.

## Supporting areas

- **Vocabularies** — `Vocabularies` / `VocabularyUpload` / `VocabularyDetail`
  (`/vocabularies…`): manage the OHDSI vocabularies that mapping searches against.
- **Monitor** — `Monitor` (`/monitor`): training + extraction dashboard. Training
  progress streams over a **WebSocket** (`getTrainingWSUrl`, see
  [background/api-layer.md](./background/api-layer.md#websocket-training-monitor));
  charts come from `src/components/charts/`.
- **UserProfile** — `/profile`: account settings.

## Data flow recap

Pages hold view state in `useState` and load it through hooks; after any mutation
(extract, cluster edit, map) the page calls the hook's refresh callback to re-pull from
the backend. There is no shared client store — see
[background/state-and-hooks.md](./background/state-and-hooks.md).
