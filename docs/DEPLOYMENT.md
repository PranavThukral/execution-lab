# Deployment

## Vercel

The repository uses [Vercel Services](https://vercel.com/docs/services), currently in Beta, to deploy the Vite frontend and FastAPI API as one project.

Import the GitHub repository into Vercel and keep the project's root at the repository root. Service-specific settings are already in `vercel.json`; do not set a project-wide frontend output directory or build command.

- `frontend/` runs `npm ci` and `npm run build`; Vercel serves its `dist` output.
- `backend/` exposes `app.main:app` using its `pyproject.toml` and `uv.lock`.
- `/api/*`, `/healthz`, `/readyz`, `/docs` and `/openapi.json` route to the API. Other paths route to the frontend.
- Non-secret configuration enables production headers and trusted-proxy client identification, disables persistent imports, and tells backend readiness that the frontend is deployed separately.
- The generated dataset is packaged with the backend. No provider credentials are needed.

The public API is stateless. Process-local limits constrain each warm backend instance; they are not a distributed quota. Hosted imports should use persistent external storage rather than a function's filesystem.

After deployment, verify the actual HTTPS URL:

```text
GET /                       -> HTML with the latest wording
GET /readyz                 -> 200 and status=ready
GET /api/v1/datasets        -> generated dataset with six sessions
POST /api/v1/simulations    -> 200 with three strategy results
GET /api/v1/exports         -> downloadable submitted result
```

Run all three example cases, check the charts, and download a result in the browser. A deployment URL is only considered verified after the checks pass.

## Docker

For a single local container, run `docker compose up --build` from the repository root. The Dockerfile builds the frontend, installs the backend, and starts Uvicorn under a non-root user. The container serves the complete app at `http://localhost:8000` and uses `/readyz` for readiness.
