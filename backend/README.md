# Sasti Dawai backend

FastAPI service for catalogue search, deterministic comparison candidates, savings requests, scan metadata, feedback, and data-source metadata. SQLite is used by default so the service can run locally without a separate database server.

## Run locally

From the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
uvicorn app.main:app --app-dir backend --reload
```

Open `http://127.0.0.1:8000/docs` for the generated API reference. The API reads the configured CSV on first startup, stores its SHA-256 and row count, and imports the catalogue rows. `DATABASE_PATH` and `CATALOGUE_CSV` can be set in the environment to choose other paths.

## Current data limits

The repository CSV does not provide a source licence or price retrieval dates. Imported prices are returned with `price_status: "undated"`; savings estimates remain unavailable until both compared prices have dates. No Kendra dataset is included. The scan endpoint accepts an image but the repository has no configured extraction provider, so it returns `unresolved`, discards the image, and directs the client to manual search. Matching cannot return `EXACT` because the catalogue does not contain verified release-type or route fields.

## Routes

- `GET /health`, `GET /ready`
- `POST /v1/scan`, `POST /v1/scan/{scan_id}/confirm`
- `POST /v1/match`, `GET /v1/search`
- `POST /v1/savings/estimate`, `POST /v1/basket/summary`
- `GET /v1/kendras/nearby`
- `POST /v1/feedback`
- `GET /v1/meta/data-sources`

Configuration is read from environment variables; see `.env.example`. Uploaded scan bytes are never written to disk or stored in the database.
