"""Fast, HTTP-free runner for reproducible dataset generation."""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pandas as pd

from opspilot.core.clock import VirtualClock
from opspilot.core.config import SimulationConfig, load_simulation_config
from opspilot.core.errors import SimulationError
from opspilot.core.ids import simulation_run_id
from opspilot.domain.models.telemetry import GroundTruthRecord, LogRecord, MetricPoint
from opspilot.simulator.chaos.ground_truth import GroundTruthWriter
from opspilot.simulator.engine.model import SimulationEngine


@dataclass(frozen=True)
class SimulationArtifacts:
    """Paths and row counts produced by one virtual simulation run."""

    run_id: str
    metrics_path: Path
    logs_path: Path
    ground_truth_path: Path
    metric_rows: int
    log_rows: int
    fault_rows: int


def run_virtual_simulation(
    *,
    config_path: Path,
    hours: int,
    seed: int,
    output_root: Path = Path("data"),
    normal_only: bool = False,
) -> SimulationArtifacts:
    """Run the configured simulator and persist Parquet metrics plus JSONL logs."""
    if hours <= 0:
        raise SimulationError("hours must be a positive integer")
    config = load_simulation_config(config_path)
    return simulate(
        config=config,
        hours=hours,
        seed=seed,
        output_root=output_root,
        normal_only=normal_only,
    )


def simulate(
    *,
    config: SimulationConfig,
    hours: int,
    seed: int,
    output_root: Path = Path("data"),
    normal_only: bool = False,
) -> SimulationArtifacts:
    """Run a validated configuration without making network calls."""
    if hours <= 0:
        raise SimulationError("hours must be a positive integer")

    total_seconds = hours * 3_600
    step_seconds = config.step_seconds
    steps = total_seconds // step_seconds
    if steps == 0:
        raise SimulationError("Simulation duration is shorter than one configured tick")

    if normal_only:
        config = config.model_copy(update={"faults": [], "decoys": []})
    clock = VirtualClock(config.start_at)
    run_id = simulation_run_id(seed, config.start_at)
    if normal_only:
        run_id = f"{run_id}-normal"
    engine = SimulationEngine(
        config,
        seed=seed,
        run_id=run_id,
        clock=clock,
    )
    metrics: list[MetricPoint] = []
    logs: list[LogRecord] = []
    for _ in range(steps):
        tick_metrics, tick_logs = engine.tick()
        metrics.extend(tick_metrics)
        logs.extend(tick_logs)
        clock.advance(step_seconds)

    end_at = config.start_at + timedelta(seconds=total_seconds)
    fault_records: list[GroundTruthRecord] = [
        engine.ground_truth(fault)
        for fault in engine.faults
        if fault.start_at < end_at
    ]

    processed_dir = output_root / "processed"
    raw_dir = output_root / "raw"
    truth_dir = output_root / "ground_truth"
    processed_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = processed_dir / f"simulation_{run_id}_metrics.parquet"
    logs_path = raw_dir / f"simulation_{run_id}_logs.jsonl"
    ground_truth_path = truth_dir / f"simulation_{run_id}_faults.jsonl"

    try:
        frame = pd.DataFrame.from_records(
            [metric.model_dump(mode="json") for metric in metrics]
        )
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        frame.to_parquet(metrics_path, index=False, compression="zstd")
        logs_path.write_text(
            "\n".join(log.model_dump_json() for log in logs) + ("\n" if logs else ""),
            encoding="utf-8",
        )
        written_faults = GroundTruthWriter().write(ground_truth_path, fault_records)
    except (OSError, ValueError, ImportError) as exc:
        raise SimulationError(f"Could not write simulation artifacts: {exc}") from exc

    return SimulationArtifacts(
        run_id=run_id,
        metrics_path=metrics_path,
        logs_path=logs_path,
        ground_truth_path=ground_truth_path,
        metric_rows=len(metrics),
        log_rows=len(logs),
        fault_rows=written_faults,
    )

