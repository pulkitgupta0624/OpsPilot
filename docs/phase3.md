# Phase 3: deep learning, log templates, and live incidents

## What this phase adds

- A CPU LSTM autoencoder trained on normal-only feature sequences, with an internal
  early-stopping split and a held-out normal run for threshold calibration.
- Per-feature reconstruction errors attached to metric alerts as `suspect_features`.
- Drain3 templates learned only from normal-only JSONL logs, with new-template and
  per-template frequency-spike signals during monitoring.
- A topology-aware alert correlator with a configurable merge window and cooldown.
- Postgres `incidents` and `alerts` tables, and a monitor command that polls the three
  simulator HTTP adapters, stores telemetry, scores it, and writes correlated incidents.

The monitor primes its rolling feature history from the latest normal-only run and shifts
that warm-up history to just before startup. New live samples continue from wall-clock time.
This avoids waiting through the 30-minute rolling baseline period for a local demo.

## Local workflow

Run the package sync after adding the optional ML extra. The PyTorch source is configured
to use CPU wheels; this phase does not require a GPU.

```powershell
uv sync --python 3.12 --extra dev --extra analysis --extra ml
uv run opspilot train --detector ml
uv run opspilot eval detection
docker compose -f compose.db.yaml up -d --wait postgres
uv run alembic upgrade head
```

Start each simulator adapter in its own PowerShell terminal:

```powershell
uv run uvicorn opspilot.simulator.services.orders.app:app --host 127.0.0.1 --port 8001
```

```powershell
uv run uvicorn opspilot.simulator.services.payments.app:app --host 127.0.0.1 --port 8002
```

```powershell
uv run uvicorn opspilot.simulator.services.inventory.app:app --host 127.0.0.1 --port 8003
```

In another terminal, start the online monitor:

```powershell
uv run opspilot monitor --detector rolling_zscore
```

The monitor also accepts `isolation_forest` and `lstm_autoencoder`. Trigger a demo fault
from another PowerShell terminal:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8002/admin/fault -ContentType "application/json" -Body '{"fault_type":"db_pool_exhaustion","duration_seconds":900,"intensity":1.0}'
```

Inspect `incidents` and `alerts` in the `opspilot` database using pgAdmin. Each metric
alert includes suspect features; log alerts include the Drain3 template and signal reason.

## Reports and showcase files

`uv run opspilot eval detection` now compares rolling z-score, Isolation Forest, and the
LSTM autoencoder. The timestamped CSV, Markdown, and score timeline remain in
`evals/reports/`. Notebook 04 reads the latest report and plots the overall comparison.

## Evaluation notes

The LSTM threshold is calibrated from held-out normal windows only. Evaluation remains
event-level and scores fault-injected runs only. Live monitoring uses a separate online
consecutive-window setting so the first threshold crossing can create a timely incident;
offline evaluation retains its own consecutive-window policy. Report observed metrics from
your local run rather than treating the initial README targets as achieved results.
