# Setup & Run

Get the frontend from clone to running, then build and test it. Commands are derived
from `package.json` scripts, `vite.config.ts`, and `Dockerfile`.

## Prerequisites

- **Node.js 20+** — the Docker build uses `node:20-alpine`; 18+ works for local dev.
- **npm** — the project pins deps with `package-lock.json`; use `npm`, not yarn/pnpm.
- A running **backend** at `http://localhost:8000` for the app to talk to. See the
  root `CLAUDE.md` for the full stack, or run everything with `docker-compose up` from
  the repo root.
- For the Storybook test project: Playwright browsers (`npx playwright install`).

## Configure

The frontend reads env vars from the **repository-root `.env`** (Vite is configured in
`vite.config.ts` to `loadEnv` from the parent directory). Document names only — never
put real secrets in docs or commit a real `.env`.

| Name | Purpose | Required | Default | Source |
|---|---|---|---|---|
| `FRONTEND_HOST` | Dev server URL; its port sets the Vite dev port | optional | `http://localhost:5173` | `vite.config.ts` |
| `BACKEND_HOST` | Target the dev `/api` proxy forwards to | optional | `http://localhost:8000` | `vite.config.ts` |
| `VITE_BACKEND_HOST` | Absolute API host baked into the **production** build; when unset the app uses the relative `/api/v1` path (served behind nginx). Also derives the training WebSocket URL. | optional | *(unset → relative `/api/v1`)* | `src/api/client.ts`, `src/api/monitoring.ts`, `Dockerfile` build arg |

> Only `VITE_`-prefixed vars are exposed to client code at build time (Vite rule).
> `FRONTEND_HOST` / `BACKEND_HOST` are consumed by the dev server config, not the app
> bundle.

## Setup

Run once from `frontend/`, and again whenever `package.json` changes:

```bash
npm install
```

## Run (development)

```bash
npm run dev            # Vite dev server with HMR; default http://localhost:5173
```

The dev server proxies `/api` → `BACKEND_HOST` with a 10-minute timeout (matching long
extraction/upload requests). Make sure the backend is up.

## Build & preview (production)

```bash
npm run build          # tsc -b && vite build → dist/
npm run preview        # serve the built dist/ locally
```

For a real production deployment (nginx image, API proxying, WebSocket handling) see
[deploy.md](./deploy.md).

## Lint & format

```bash
npm run lint           # eslint .
npm run format         # prettier --write .
npm run format:check   # prettier --check .   (CI-style, no writes)
```

Prettier config: double quotes, 2-space indent, `printWidth: 120`, `trailingComma: es5`.

## Test

```bash
npm run test           # vitest run — both projects (unit + storybook)
npm run test:watch     # vitest in watch mode
npm run test:coverage  # with coverage
npm run test -- src/utils/__tests__/dateUtils.test.ts   # single file
```

Vitest defines **two projects** in `vite.config.ts`:

- **unit** — node environment; matches `src/**/*.test.{ts,tsx}` and
  `src/**/__tests__/**`.
- **storybook** — runs every `*.stories.*` in a real **Chromium** browser via
  Playwright. This project needs browsers installed (`npx playwright install`); without
  them the storybook project fails while unit tests still pass.

## Storybook

```bash
npm run storybook          # dev server on :6006
npm run build-storybook    # static build
```
