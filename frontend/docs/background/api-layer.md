# API Layer

How the frontend talks to the backend: one typed `fetch` wrapper plus one module per
backend domain. Lives in `src/api/`; import everything from the barrel `@/api`
(`src/api/index.ts`).

## Design

No axios, no react-query, no SWR — plain `fetch` behind a thin typed wrapper. Every
call goes through `apiRequest()` in `src/api/client.ts`, the single choke point for:

- **Base URL** — `API_BASE_URL` is `${VITE_BACKEND_HOST}/api/v1` when that env var is
  set (prod/docker with an absolute host), otherwise the relative `/api/v1` (dev proxy
  or nginx same-origin). See `src/api/client.ts:7`.
- **Auth header** — attaches `Authorization: Bearer <access_token>` from
  `localStorage` unless `skipAuth` is passed.
- **JSON** — sets `Content-Type: application/json` for string bodies; parses JSON
  responses, returning `{}` for empty bodies.
- **Errors** — non-OK responses throw `Error(detail)` using the backend's `detail`
  field when present, else `HTTP <status>`.

## Token storage & refresh

Tokens live in `localStorage` under `access_token` / `refresh_token` (helpers
`getToken`/`setToken`/`getRefreshToken`/`setRefreshToken`/`clearToken`).

On a `401`, `apiRequest` calls `refreshAccessToken()` and retries the original request
**once** with `skipRefresh: true` (prevents infinite loops):

- Concurrent 401s are de-duplicated — a module-level `isRefreshing` flag + shared
  `refreshPromise` mean many in-flight requests await a **single** refresh call.
- If the refresh token is missing or rejected, tokens are cleared and the client
  throws `"Session expired. Please log in again."` — the one signal the auth layer
  treats as a genuine logout (see [routing-and-auth.md](./routing-and-auth.md)).

`RequestOptions` extends `RequestInit` with two internal flags: `skipAuth` (public
endpoints) and `skipRefresh` (set on the retry).

## Domain modules

One file per backend domain, each exporting typed functions that wrap `apiRequest`:

| Module | Covers |
|---|---|
| `auth.ts` | login, register, logout, `getCurrentUser` |
| `datasets.ts` | dataset CRUD, labels, stats |
| `records.ts` | dataset records (the unstructured text rows) |
| `sourceTerms.ts` | extracted source terms per record |
| `extraction.ts` | start/cancel record & dataset extraction jobs, poll status |
| `clusters.ts` | cluster CRUD, drag-drop cluster membership |
| `mappings.ts` | map clusters/terms to OHDSI concepts, concept search |
| `vocabularies.ts` | vocabulary upload/list/detail, concept queries |
| `monitoring.ts` | training runs, extraction dashboard, training WebSocket URL |
| `client.ts` | the wrapper above; also re-exported for token helpers |

## File uploads

Dataset/vocabulary uploads do **not** use `fetch` — they use `XMLHttpRequest` to get
upload-progress events, with a 10-minute timeout. This is why the dev proxy and nginx
both allow long timeouts and large bodies (see [deploy.md](./deploy.md)).

## WebSocket (training monitor)

Training progress streams over a WebSocket, not REST. `getTrainingWSUrl(token)` in
`src/api/monitoring.ts:117` builds the URL: it swaps `http`→`ws` on `VITE_BACKEND_HOST`
when set, else derives `ws`/`wss` from `window.location`, and hits
`/api/v1/bioner/ws/training`. The access token is passed as a `?token=` query param
because the browser WebSocket API can't set headers — a documented limitation in that
file. nginx has a dedicated `location /api/v1/bioner/ws/` block to preserve the upgrade
handshake (see [deploy.md](./deploy.md)).

## Conventions

- Add a new endpoint to its domain module (or create a new module + export it from
  `src/api/index.ts`); never call `fetch` directly from components or pages.
- Keep request/response types in `src/types/` and import them into the module.
- Let errors propagate — callers (hooks/pages) surface them via toasts.
