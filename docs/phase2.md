# Phase 2: ingestion and classical detection

## Data flow

```text
Phase 1 Parquet / JSONL ──► file importer ──► Postgres metrics, logs, fault labels
                                                         │
                                                         └──► time-range query / Parquet export

Normal-only runs ──► sliding windows ──► rolling z-score and Isolation Forest
Fault-injected runs ───────────────────► thresholded alerts ──► event-level report
```

## Storage design

- Metric rows are normalized as `(run_id, service, name, ts, value)` and keyed by all
  identifying columns. The run ID is part of the key because reproducible runs share the
  same simulated timestamps.
- Log rows use a SHA-256 record key so repeated imports and overlapping live log polls are
  idempotent.
- Ground-truth intervals are stored with each run and indexed by run, service, and start.
- SQLAlchemy adapters implement the domain store ports. Alembic owns schema changes.

## Detection design

- Windows default to 60 seconds with a 10-second stride.
- Every statistic is computed from a trailing window. Baseline z-scores use a shifted
  rolling window, so the current and future samples cannot enter the baseline.
- Training data must come from a run generated with `--normal-only`. Thresholds are
  calibrated using a held-out normal run when available; a single normal run uses a
  chronological holdout and records that choice in the model metadata.
- Evaluation scores only fault-injected runs, keeping the normal training/validation runs
  out of the test results. Consecutive threshold crossings are grouped into alert episodes.
- Model artifacts are versioned under `data/models/<detector>/`; the JSON registry points
  to each detector's latest artifact.

## Local workflow

Run commands from the project root. Start the local Postgres service, apply migrations, and
import the Phase 1 data if you want to demonstrate the database path:

```powershell
docker compose -f compose.db.yaml up -d --wait postgres
uv run alembic upgrade head
uv run opspilot data ingest --metrics <metrics.parquet> --logs <logs.jsonl> --ground-truth <faults.jsonl>
```

Create independent normal runs, train, and evaluate:

```powershell
uv run opspilot simulate --virtual --normal-only --hours 24 --seed 11
uv run opspilot simulate --virtual --normal-only --hours 24 --seed 12
uv run opspilot train --detector ml
uv run opspilot eval detection
```

The evaluation writes a CSV, Markdown results table, and Parquet score timeline to
`evals/reports/`.

