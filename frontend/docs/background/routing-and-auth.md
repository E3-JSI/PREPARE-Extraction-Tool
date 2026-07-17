# Routing & Auth

How routes are defined and guarded, and how the JWT session lifecycle works. Code:
`src/pages/App/`, `src/hooks/useAuth.ts`, `src/components/AuthProvider/`,
`src/components/ProtectedRoute/`.

## Routing

`src/pages/App/index.tsx` is the router. Structure, outermost first:

```
BrowserRouter
  AuthProvider              (auth context for the whole tree)
    Suspense fallback       (spinner while a lazy route loads)
      Routes
```

- **Lazy routes** — every page is `React.lazy(() => import("pages/…"))`, so each screen
  is a separate bundle loaded on demand under one `<Suspense>`.
- **Public vs protected** — `/login` is the only public route. Every other route wraps
  its element in `<ProtectedRoute>`.
- **Redirects** — `/` and any unknown path (`*`) `Navigate` to `/datasets`.

### Route table

| Path | Page |
|---|---|
| `/login` | `Login` (public) |
| `/datasets` | `Datasets` |
| `/datasets/upload` | `DatasetUpload` |
| `/datasets/:datasetId` | `DatasetOverview` |
| `/datasets/:datasetId/records` | `DatasetTermExtraction` |
| `/datasets/:datasetId/clusters` | `DatasetTermClustering` |
| `/datasets/:datasetId/mapping` | `DatasetConceptMapping` |
| `/vocabularies` | `Vocabularies` |
| `/vocabularies/upload` | `VocabularyUpload` |
| `/vocabularies/:vocabularyId` | `VocabularyDetail` |
| `/monitor` | `Monitor` |
| `/profile` | `UserProfile` |

The `/datasets/:datasetId/*` sequence is the core workflow — see [workflow.md](../workflow.md).

## ProtectedRoute

`src/components/ProtectedRoute/` reads `useAuth()`. While auth is still resolving
(`isLoading`) it renders a loader; once resolved it renders the children if
`isAuthenticated`, otherwise redirects to `/login`. This is the single gate — pages
themselves assume an authenticated user.

## Auth lifecycle

`AuthProvider` (`src/components/AuthProvider/`) is a thin wrapper that puts the value
from `useAuthProvider()` onto `AuthContext`. Consumers call `useAuth()`, which throws if
used outside the provider. The context exposes:
`{ user, isLoading, isAuthenticated, login, register, logout }`.

- **Bootstrap on mount** — if an `access_token` exists in `localStorage`,
  `useAuthProvider` calls `getCurrentUser()` to hydrate `user`. Crucially, it only
  clears tokens when the error is exactly the `"Session expired…"` message thrown by the
  API client (i.e. a real 401 whose refresh also failed). Transient errors (network,
  5xx) keep the session intact and just log — a still-valid session is never wiped by a
  blip. See `src/hooks/useAuth.ts`.
- **login** — posts credentials, stores `access_token` + `refresh_token`, then hydrates
  `user`.
- **register** — registers, then immediately logs in with the same credentials.
- **logout** — calls the API logout, then always clears `user` in a `finally` (so a
  failed server call can't leave the UI "logged in"). Token teardown on the client side
  is handled via `clearToken` / the 401 path.

## Token refresh

The heavy lifting lives in the API client, not here: `apiRequest` auto-refreshes on
`401`, queues concurrent requests behind one refresh, and only surfaces logout when the
refresh token is also dead. Details in [api-layer.md](./api-layer.md). Tokens are stored
in `localStorage`; a failed refresh → cleared tokens → next `useAuth` bootstrap or
`ProtectedRoute` check sends the user to `/login`.
