# State & Hooks

How the app manages state and loads data. Short version: **React Context for auth,
component `useState` for everything else, custom hooks to load and refetch.** No Redux,
Zustand, SWR, or react-query.

## The state model

- **Global state = auth only.** `AuthProvider` puts the current user + auth actions on
  a React Context (see [routing-and-auth.md](./routing-and-auth.md)).
- **Everything else is local.** Each page owns its data via `useState` and asks a hook
  to fill it. There is no client-side cache or store — navigate away and the state is
  gone; navigate back and the hook refetches.
- **Refetching is manual.** Hooks expose refresh callbacks (e.g. `refreshRecords`,
  `fetchStats`). After a mutation, the page calls them to re-pull fresh data. This is
  deliberate: the flow of "act → refetch" is explicit rather than reactive.

## Data-loader hooks

Each wraps one or more API modules, holds `data` / `isLoading` / `error`, and exposes a
refresh function. Found in `src/hooks/`:

| Hook | Loads |
|---|---|
| `useDatasets` | dataset list + create/delete |
| `useRecords` | paginated records for a dataset |
| `useSourceTerms` | source terms (extracted) for a record/dataset |
| `useVocabularies` | vocabulary list |
| `useVocabularyConcepts` | concepts within a vocabulary |
| `useDatasetExtractionJob` | current extraction-job state for a dataset |
| `usePageTitle` | sets `document.title` per page |
| `useToast` | transient toast notifications (paired with the `Toast` component) |
| `useAuth` | consumes the auth context (see routing-and-auth) |

Pattern: call inside `useEffect` on mount / when an id changes; guard against setState
after unmount with an `active` flag or `AbortController`.

## `useExtractionPolling`

The most involved hook (`src/hooks/useExtractionPolling.ts`). It runs and tracks NER
extraction jobs — both single-record and whole-dataset — and survives navigation.

Key behaviours:

- **Single record** — `extractTermsForRecord()` calls the API, then refreshes the
  record's terms, the record list, and stats.
- **Whole dataset** — `extractTermsForDataset()` starts a job, gets a `job_id`, then
  `pollExtractionJob()` loops every **2 s** hitting the status endpoint until the job is
  `completed`/`cancelled`/`failed`. Every 5th poll it also refreshes the record list so
  progress is visible.
- **Resume across reload/navigation** — the active `job_id` is persisted in
  `localStorage` under `extractionJob-<datasetId>`. A mount-only effect reads it and
  resumes polling. On unmount (navigation) the loop stops **without** clearing
  `localStorage`, so returning to the page resumes the same job; on normal completion
  the key is removed.
- **Already-running guard** — if starting a job returns "already running", it fetches
  the active job and attaches to it instead of erroring.
- **Cancellation** — `cancelDatasetExtraction()` calls the cancel endpoint; a
  `cancelledRef` prevents state updates after unmount.

> Note: this hook uses `localStorage` for the job id, whereas the frontend `CLAUDE.md`
> mentions `sessionStorage` — the code is the source of truth (`localStorage`).

## Conventions

- Put reusable data-loading logic in a hook, not inline in a page.
- Return `{ data, isLoading, error, refresh }`-shaped objects for consistency.
- Guard async setState against unmount.
- Surface errors to the user via `useToast`, don't swallow them.
