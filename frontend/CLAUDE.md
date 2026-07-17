# CLAUDE.md — frontend

React 19 + Vite SPA for the extract → cluster → map workflow. See root `CLAUDE.md` for the cross-service picture.

<!-- docs:start -->
## Documentation

Human + agent docs live in [`docs/`](./docs/README.md) — read these before deep work:

- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — system map + validated Mermaid diagram
- [docs/setup-and-run.md](./docs/setup-and-run.md) — env vars, commands, test projects
- [docs/workflow.md](./docs/workflow.md) — the extract → cluster → map workflow across pages
- [docs/background/](./docs/background/) — deep dives: [api-layer](./docs/background/api-layer.md), [state-and-hooks](./docs/background/state-and-hooks.md), [routing-and-auth](./docs/background/routing-and-auth.md)
- [docs/components.md](./docs/components.md) · [docs/deploy.md](./docs/deploy.md)

Stack conventions: [.claude/project-rules/react-vite.md](./.claude/project-rules/react-vite.md).
@.claude/project-rules/react-vite.md
<!-- docs:end -->

## Stack

React 19 · Vite 7 · TypeScript 5.8 (strict) · React Router 7 · Vitest 3 · Storybook 9 · ESLint 9 (flat) ·
Prettier. UI: @dnd-kit (drag-drop clustering), Recharts, FontAwesome, date-fns, classnames. CSS Modules.
Package manager: **npm** (`package-lock.json`).

## Commands

```bash
npm install
npm run dev                 # Vite dev server; proxies /api → BACKEND_HOST (default http://localhost:8000)
npm run build               # tsc -b && vite build → dist/
npm run lint                # eslint .
npm run format              # prettier --write .   (format:check to verify)
npm run test                # vitest run (unit + storybook story tests)
npm run test -- src/utils/__tests__/dateUtils.test.ts   # single test file
npm run storybook           # :6006
```

## Conventions (don't violate — details in docs/)

- **Styling**: `DESIGN.md` is the authority. Reference `var(--…)` tokens (never raw hex); BEM class names;
  one `styles.module.css` per component. Label colors via `getLabelColorClass` → `label1`–`label9`.
- **API**: never call `fetch` directly — go through `src/api/` (`client.ts` attaches the Bearer token and
  auto-refreshes on 401). See [docs/background/api-layer.md](./docs/background/api-layer.md).
- **State**: React Context holds auth only; everything else is component `useState` + custom hooks with
  manual refetch. No Redux/Zustand/SWR. See [docs/background/state-and-hooks.md](./docs/background/state-and-hooks.md).
- **Routing**: routes are `React.lazy` + `Suspense`; every route except `/login` is wrapped in
  `ProtectedRoute`. JWT tokens in localStorage; failed refresh → logout.
- **Path aliases** (`tsconfig.app.json`): `@/`, `@components/`, `@pages/`, `@hooks/`, `@api/`, `@types/`, `@assets/`.
- **Prettier**: double quotes, 2-space, `printWidth: 120`, `trailingComma: es5`.
