# Phase 6: Product, DevOps, Evaluation, and Polish

## Phase 6A deliverable in this workspace

This first vertical slice adds a FastAPI product API and an API-backed Streamlit
dashboard. It builds on the PostgreSQL incident and metric stores, the Phase 4
retriever, and the Phase 5 agent runtime already in the project.

- FastAPI app factory, OpenAPI docs, API-key protection for `/v1/*`, request IDs,
  and a consistent JSON error envelope.
- Incident list/detail, alert timeline, agent trace and audit history, human approval,
  agent rerun, and bounded Server-Sent Events updates.
- Detection status and recent metrics, cited knowledge search, latest local evaluation
  reports, and opt-in simulator fault injection.
- Streamlit pages for overview charts, incidents and approvals, agent trace, knowledge,
  chaos control, and evaluation reports. The dashboard calls the HTTP API and does not
  connect directly to PostgreSQL or the agent runtime.

The rest of the README's Week 6 checklist remains open: Docker/Compose runtime review
and clean-clone demo, CI, integration and evaluation gates, nightly full evaluation,
external tracing and Prometheus/Grafana, full scenario analysis, and release
documentation/demo.

The Compose setup described below is now present, but it has not been built or run in
this workspace. Treat it as ready for your local review, not as runtime-verified.

## Prerequisites

Start PostgreSQL, the simulator services, and the Phase 3 monitor as described in
[`phase3.md`](phase3.md). The API reads persisted incidents and metrics from PostgreSQL.
The knowledge page also needs the Phase 4 local RAG index. The local environment below
uses the same `%LOCALAPPDATA%` paths used by the earlier phase guides.

## Install the dashboard extra

In PowerShell, from the project root, use the same Python 3.12 environment as Phases 3–5.
If the prompt shows `(opspilot)`, run `deactivate` first so `uv` can update the
environment cleanly.

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "OpsPilot-venv"
$env:LANGGRAPH_STRICT_MSGPACK = "true"
uv sync --python 3.12 --extra dev --extra analysis --extra ml --extra rag --extra agents --extra dashboard --link-mode copy
$env:OPSPILOT_RAG_INDEX_DIR = Join-Path $env:LOCALAPPDATA "OpsPilot-rag"
```

## Start the API

From the project root, use a new PowerShell window for the API.

Use a local-only key for this demo. Chaos controls are disabled by default; enable them
only when you want the dashboard to inject faults into your local simulator.

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "OpsPilot-venv"
$env:LANGGRAPH_STRICT_MSGPACK = "true"
$env:OPSPILOT_API_KEY = "local-dev-change-this-key"
$env:OPSPILOT_RAG_INDEX_DIR = Join-Path $env:LOCALAPPDATA "OpsPilot-rag"
$env:OPSPILOT_ENABLE_CHAOS_API = "true"
uv run uvicorn opspilot.api.main:app --host 127.0.0.1 --port 8000
```

Keep that PowerShell window open. In another window, verify the API and authenticated
incident route:

```powershell
$env:OPSPILOT_API_KEY = "local-dev-change-this-key"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/ready"
Invoke-RestMethod -Headers @{ "X-API-Key" = $env:OPSPILOT_API_KEY } -Uri "http://127.0.0.1:8000/v1/incidents"
```

OpenAPI UI is available at `http://127.0.0.1:8000/docs`.

## Start the dashboard

In a second PowerShell window from the project root, keep the API key identical to the
one in the API window, then start Streamlit:

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "OpsPilot-venv"
$env:OPSPILOT_API_URL = "http://127.0.0.1:8000"
$env:OPSPILOT_API_KEY = "local-dev-change-this-key"
uv run streamlit run src/opspilot/dashboard/app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. Choose an incident to inspect its alerts and agent plan;
approve or reject only after reviewing that plan. Chaos Control changes simulator
state, so use it only for a demo run where you intend to trigger a fault.

## API routes

All `/v1/*` routes require the `X-API-Key` header. `/health` and `/ready` are public;
`/ready` checks the database connection. FastAPI serves the interactive schema at
`/docs`.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/v1/incidents` | Filter and paginate incidents |
| `GET` | `/v1/incidents/{id}` | Incident, alert timeline, and agent summary |
| `GET` | `/v1/incidents/{id}/trace` | Agent graph events and audit events |
| `GET` | `/v1/incidents/{id}/stream` | Bounded SSE snapshots while an incident is active |
| `POST` | `/v1/incidents/{id}/approval` | Submit a human approval or rejection |
| `POST` | `/v1/incidents/{id}/rerun` | Rerun an agent for an open incident |
| `GET` | `/v1/detection/status` | Latest detector output and open incident count |
| `GET` | `/v1/metrics/{service}` | Recent metric series for a configured service |
| `POST` | `/v1/kb/search` | Search indexed knowledge with citations |
| `GET` | `/v1/evals/latest` | Read bounded excerpts from local eval reports |
| `POST` | `/v1/simulator/faults` | Inject a simulator fault when the opt-in flag is enabled |

Errors use `{"error":{"code":"...","message":"..."}}` and include an
`X-Request-ID` response header for support/debugging.

## Local review checklist

- [ ] `/health` returns `status: ok` and `/ready` returns `status: ready`.
- [ ] The authenticated incident request returns persisted incidents (or an empty list).
- [ ] Dashboard metrics and incident pages load from the API.
- [ ] Agent trace and knowledge search show citations when data is available.
- [ ] Approval/rejection works against an incident in the matching agent state.
- [ ] Chaos Control is refused when disabled and reaches only the local simulator when enabled.
- [ ] Evaluation page displays available local reports.

## Docker Compose demo

The Compose stack uses a separate project name and separate PostgreSQL/data volumes
from `compose.db.yaml`, so it does not replace the database used by the earlier local
workflow. It starts three internal-only simulator services, a one-time bootstrap,
the ingestion/detection worker, the API, and the dashboard. The bootstrap migrates
PostgreSQL, generates a normal baseline, trains the rolling z-score detector, and
builds the local knowledge index. The first build and first knowledge-index bootstrap
need internet access to download packages and the embedding model. The simulator and
dashboard use separate images that omit the agent/RAG/PyTorch dependencies.

From the project root, if GNU Make is installed, `make demo` works without a `.env`
file: it creates an ignored `.env` with a random local API key, so later Compose
commands use the same key. To set a custom API key or enable chaos controls, create
`.env` and edit it. This conditional copy preserves an existing `.env` file:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Before starting, make sure Docker Desktop is running and local processes are not
already using ports 8000 or 8501. Without GNU Make, create/edit `.env` as shown above,
then start the stack with:

```powershell
docker compose config --quiet
docker compose up --build --detach
docker compose ps
docker compose logs --tail 100 bootstrap worker
```

Open `http://127.0.0.1:8501`. The API is at `http://127.0.0.1:8000`; its OpenAPI UI
is at `/docs`. Set `OPSPILOT_ENABLE_CHAOS_API=true` in `.env` and run
`docker compose up --detach` again only if you want the Chaos Control page to inject a
fault into these local simulator containers. The simulators and PostgreSQL are not
published on host ports.

Stop the containers while retaining demo data with:

```powershell
docker compose down
```

No API, dashboard, dependency install, Docker, or test command has been run in this
workspace. Run the commands locally and share any output or errors before treating the
Phase 6 slices as verified.
