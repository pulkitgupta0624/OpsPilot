# OpsPilot architecture

## Phase 1 boundaries

Phase 1 contains a deterministic simulator and a small HTTP adapter. The simulator is the
source of modelled service state; it does not inspect or modify the host machine.

```text
CLI / FastAPI adapters
        │
        ├── parse configuration and validate requests
        ▼
Simulator engine ─────── Load profile
        │                 Fault catalog
        │                 Service topology
        ├── MetricPoint
        ├── LogRecord
        └── GroundTruthRecord
                │
                ├── Parquet metrics
                └── JSONL logs and fault labels
```

## Module responsibilities

- `core/` owns configuration loading, typed application errors, clocks, and stable IDs.
- `domain/` owns shared enums and validated telemetry contracts. It does not depend on
  FastAPI, pandas, or the simulation engine.
- `simulator/engine/` calculates service state and metrics from load and active faults.
- `simulator/chaos/` defines fault behavior, schedule construction, and ground-truth output.
- `simulator/loadgen/` creates seeded seasonality, Poisson variation, and normal traffic bursts.
- `simulator/services/` adapts the engine to the service health, metrics, and admin endpoints.
- `simulator/virtual_runner.py` runs the engine without HTTP and persists training data.
- `cli.py` is a thin user-facing entry point; it delegates simulation work to the runner.

## Design decisions

- Simulation time is injected through a clock. The virtual runner advances a virtual clock;
  HTTP adapters use a UTC system clock.
- Randomness comes from a per-run NumPy generator initialized with the requested seed.
- Fault types implement one shared interface and declare the actions that resolve them.
  Unsupported actions leave the fault active, so later verification can detect a bad fix.
- YAML contains tunable service and fault parameters; domain constraints are checked at load time.
- Generated datasets are ignored by Git. Small intentional fixtures can be added separately.
- The simulator has no shell, host-process, or cloud control surface.

