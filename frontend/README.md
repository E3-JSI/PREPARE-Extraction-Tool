# Frontend

The frontend for the PREPARE Extraction Tool, built with React 19, TypeScript, and Vite.

<!-- docs:start -->
## 📚 Documentation

Full frontend docs live in [`docs/`](./docs/README.md):

- [Architecture](./docs/ARCHITECTURE.md) — system map + diagram
- [Setup & Run](./docs/setup-and-run.md) — install, configure, run, build, test
- [Workflow](./docs/workflow.md) — the extract → cluster → map user flow
- Background: [API layer](./docs/background/api-layer.md) · [State & hooks](./docs/background/state-and-hooks.md) · [Routing & auth](./docs/background/routing-and-auth.md)
- Reference: [Components](./docs/components.md) · [Deploy](./docs/deploy.md)
- [DESIGN.md](./DESIGN.md) — the authority for UI styling & tokens
<!-- docs:end -->

## ☑️ Requirements

- [Node.js 18+](https://nodejs.org/)
- [npm](https://www.npmjs.com/) (comes with Node.js)

## 🛠️ Setup

Run this once from the `frontend/` folder (or whenever `package.json` changes):

```bash
npm install
```

## 🏗️ Development

Start the dev server with hot module replacement (changes reflect instantly in the browser):

```bash
npm run dev
```

The app will be available at **http://localhost:5173** by default.

> The frontend talks to the backend API at `http://localhost:8000`. Make sure the backend is also running in a separate terminal — see [backend/README.md](../backend/README.md).

## 🚀 Production

To start the app in production mode, run the following command in the terminal:

```bash
npm run build         # Compile and bundle for production (output in /dist)
npm run preview       # Preview the production build locally
```

> For a full production setup, use Docker instead — see the root [README.md](../README.md).

## 🐳 Dockerize

To dockerize the app, run the following command in the terminal:

```bash
# build the docker image
docker build -t frontend .

# run the docker container
docker run -d --name frontend -p 3000:3000 frontend
```
