# Deploy

How the SPA is built and served in production: a static bundle behind nginx, which also
proxies the API and the training WebSocket to the backend. Sources: `Dockerfile`,
`nginx.conf`, and the `frontend` service in the root `docker-compose.yaml`.

## Build → serve model

There is no Node server in production. `npm run build` emits a static `dist/`, and nginx
serves it. Two-stage `Dockerfile`:

1. **builder** (`node:20-alpine`) — `npm ci --include=dev`, copy source, `npm run build`
   → `/app/dist`.
2. **runtime** (`nginx:alpine`) — copy `dist` to `/usr/share/nginx/html`, copy
   `nginx.conf` to `/etc/nginx/conf.d/default.conf`, expose **3000**.

### Build-time config

`VITE_BACKEND_HOST` is a **build arg** baked into the bundle (`ARG`/`ENV` in the
`Dockerfile`). Because Vite inlines env at build time, changing the API host means
**rebuilding** the image, not restarting it.

- **Leave it unset** (the docker-compose default) → the app uses the relative `/api/v1`
  path and nginx proxies to the backend on the same origin. This is the intended
  production setup.
- **Set it** only if the frontend must call an absolute, different-origin API host.

## nginx (`nginx.conf`)

Listens on **3000**, serves the SPA, and proxies to the `backend` service over the
Docker network. Key blocks:

- **SPA routing** — `location /` → `try_files $uri $uri/ /index.html`, so client-side
  routes deep-link correctly.
- **REST proxy** — `location /api/v1/` → `http://backend:8000/api/v1/` with 600 s
  read/send timeouts and `proxy_request_buffering off` (streams large uploads).
- **WebSocket proxy** — `location /api/v1/bioner/ws/` is a **separate, longest-prefix**
  block that sets the `Upgrade`/`Connection` headers to preserve the WS handshake, with
  3600 s timeouts (the training socket sits idle between log events). Without this block
  nginx would forward the handshake as a plain GET and the backend would 404.
- **Uploads** — `client_max_body_size 2048M` (2 GB) to match large dataset/vocabulary
  files.
- **Static caching** — 1-year immutable cache for hashed assets; gzip on.
- **Security headers** — `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options:
  nosniff`, `X-XSS-Protection`.

## docker-compose (root)

The `frontend` service (`PREPARE-FRONTEND`) builds from `./frontend`, publishes
`3000:3000`, restarts `unless-stopped`, and has a healthcheck curling
`http://localhost:3000/`. It joins the `prepare-public` and default networks so nginx can
reach `backend:8000`.

Run the full stack from the repo root:

```bash
docker-compose up -d          # builds + starts frontend, backend, bioner, PG, ES
```

Frontend is then at **http://localhost:3000**. See the root `CLAUDE.md`/`README.md` for
the complete stack, migrations, and seeding.

## Standalone image

```bash
docker build -t frontend .                       # from frontend/
docker run -d --name frontend -p 3000:3000 frontend
```

Standalone, nginx still expects a reachable `backend` host on the Docker network — run it
alongside the backend (e.g. via compose) rather than in isolation.
