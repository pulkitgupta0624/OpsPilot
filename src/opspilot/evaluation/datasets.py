"""Load generated simulation files with run boundaries preserved."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class SimulationDataset:
    """Combined metrics and fault labels with their source artifact paths."""

    metrics: pd.DataFrame
    faults: pd.DataFrame
    metric_paths: tuple[Path, ...]


def load_simulation_dataset(data_root: Path = Path("data")) -> SimulationDataset:
    """Load all Phase 1 Parquet runs and matching ground-truth JSONL files."""
    processed_dir = data_root / "processed"
    truth_dir = data_root / "ground_truth"
    metric_paths = tuple(sorted(processed_dir.glob("simulation_*_metrics.parquet")))
    if not metric_paths:
        raise FileNotFoundError(
            f"No simulation metric Parquet files found in {processed_dir}. "
            "Run the Phase 1 simulator first."
        )

    metric_frames: list[pd.DataFrame] = []
    fault_records: list[dict[str, object]] = []
    for metric_path in metric_paths:
        frame = pd.read_parquet(metric_path)
        if "run_id" not in frame:
            frame["run_id"] = _run_id_from_metrics_path(metric_path)
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        metric_frames.append(frame)

        run_id = str(frame["run_id"].iloc[0]) if not frame.empty else _run_id_from_metrics_path(metric_path)
        truth_path = truth_dir / f"simulation_{run_id}_faults.jsonl"
        if not truth_path.exists() or truth_path.stat().st_size == 0:
            continue
        truth_frame = pd.read_json(truth_path, lines=True, convert_dates=False)
        if truth_frame.empty:
            continue
        truth_frame["run_id"] = run_id
        truth_frame["start"] = pd.to_datetime(truth_frame["start"], utc=True)
        truth_frame["end"] = pd.to_datetime(truth_frame["end"], utc=True)
        fault_records.extend(truth_frame.to_dict(orient="records"))

    metrics = pd.concat(metric_frames, ignore_index=True)
    faults = pd.DataFrame.from_records(fault_records)
    if not faults.empty:
        faults["start"] = pd.to_datetime(faults["start"], utc=True)
        faults["end"] = pd.to_datetime(faults["end"], utc=True)
    return SimulationDataset(metrics=metrics, faults=faults, metric_paths=metric_paths)


def _run_id_from_metrics_path(path: Path) -> str:
    prefix = "simulation_"
    suffix = "_metrics.parquet"
    if path.name.startswith(prefix) and path.name.endswith(suffix):
        return path.name[len(prefix) : -len(suffix)]
    return path.stem

