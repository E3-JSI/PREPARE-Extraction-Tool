# Frontend Docs

Documentation for the PREPARE Extraction Tool **frontend** — a React 19 + Vite SPA for
the extract → cluster → map workflow. Human-first prose that AI agents also navigate.
For the cross-service picture (backend, bioner, data stores) see the repository-root
`CLAUDE.md`.

## Start here

| Doc | Purpose |
|---|---|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | One-page system map + diagram; find the right subsystem fast |
| [setup-and-run.md](./setup-and-run.md) | Prerequisites, env vars, install, run, build, lint, test |
| [workflow.md](./workflow.md) | The upload → extract → cluster → map user workflow across pages |

## Subsystem deep dives

| Doc | Purpose |
|---|---|
| [background/api-layer.md](./background/api-layer.md) | The `fetch` client, token refresh, and per-domain API modules |
| [background/state-and-hooks.md](./background/state-and-hooks.md) | State model, data-loader hooks, extraction-job polling |
| [background/routing-and-auth.md](./background/routing-and-auth.md) | Router, lazy/protected routes, JWT session lifecycle |

## Reference

| Doc | Purpose |
|---|---|
| [components.md](./components.md) | Reusable component library, charts, label colors, DESIGN.md rules |
| [deploy.md](./deploy.md) | Production build + nginx serving + API/WebSocket proxying |

## See also

- `../DESIGN.md` — the authority for all UI styling and design tokens.
- `../CLAUDE.md` — quick orientation for AI agents working in `frontend/`.
- Repository-root `CLAUDE.md` — the three-service architecture and full-stack run.
