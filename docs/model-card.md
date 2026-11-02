# OpsPilot anomaly detector model card (draft)

## Intended use

Portfolio demonstration using simulated telemetry from the OpsPilot orders, payments, and
inventory services. These detectors are not validated for production traffic.

## Models

| Detector | Method | Training data |
|---|---|---|
| `rolling_zscore` | Maximum absolute past-only rolling z-score | Normal-only simulator runs |
| `isolation_forest` | Isolation Forest over standardized window features | Normal-only simulator runs |
| `lstm_autoencoder` | LSTM sequence reconstruction error | Normal-only simulator runs |

## Data and leakage controls

- Training and threshold calibration use normal-only simulation runs.
- When two or more normal runs exist, calibration uses a held-out run; the training split is
  kept separate by run ID.
- Fault-injected runs are reserved for event-level evaluation.
- The online monitor warms its rolling history from one normal-only run, shifted to current
  wall-clock time for the local demo.

## Metrics

Populate this section from the latest `evals/reports/detection_results_*.md` after running
the Phase 3 workflow locally.

| Detector | Event precision | Event recall | Event F1 | Median delay (s) | False alarms/day |
|---|---:|---:|---:|---:|---:|
| `rolling_zscore` | Pending local run | Pending local run | Pending local run | Pending local run | Pending local run |
| `isolation_forest` | Pending local run | Pending local run | Pending local run | Pending local run | Pending local run |
| `lstm_autoencoder` | Pending local run | Pending local run | Pending local run | Pending local run | Pending local run |

## Limitations

- Data is synthetic and the evaluation contains a small number of fault events.
- The LSTM reconstruction score is an anomaly signal, not a causal diagnosis.
- Drain3 templates and frequency baselines come from the available normal-only log runs.
- Live monitoring is a local demonstration with bounded in-memory state and a single Postgres
  instance; it has not been load-tested.

## Reproducibility

Record the local model artifact directory, `metadata.json`, detection configuration, report
path, and Python/package lockfile with any results you publish.
