"""Train Phase 2 detectors on normal-only windows and calibrate on held-out normal data."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd

from opspilot.core.clock import SystemClock
from opspilot.detection.config import DetectionSettings, load_detection_settings
from opspilot.detection.features.windowing import WindowConfig, build_feature_windows
from opspilot.detection.models.base import BaseDetector
from opspilot.detection.models.isolation_forest import IsolationForestDetector
from opspilot.detection.models.lstm_autoencoder import LSTMAutoencoderDetector
from opspilot.detection.models.zscore import RollingZScoreDetector
from opspilot.detection.registry import DetectorRegistry
from opspilot.evaluation.datasets import SimulationDataset, load_simulation_dataset

SUPPORTED_DETECTORS = {
    "rolling_zscore",
    "isolation_forest",
    "lstm_autoencoder",
}


@dataclass(frozen=True)
class TrainedArtifact:
    """Summary of a saved, calibrated detector version."""

    name: str
    threshold: float
    artifact_dir: Path
    train_rows: int
    validation_rows: int


def train_classical_detectors(
    *,
    detector: str = "ml",
    data_root: Path = Path("data"),
    model_root: Path = Path("data/models"),
    config_path: Path = Path("configs/detection.yaml"),
) -> list[TrainedArtifact]:
    """Train selected detectors using only known-normal simulation runs."""
    settings = load_detection_settings(config_path)
    dataset = load_simulation_dataset(data_root)
    features = build_feature_windows(
        dataset.metrics,
        WindowConfig(
            window_seconds=settings.window_seconds,
            stride_seconds=settings.stride_seconds,
            baseline_seconds=settings.baseline_seconds,
        ),
    )
    normal_runs = _normal_run_ids(dataset)
    normal = features.loc[features["run_id"].astype(str).isin(normal_runs)].copy()
    if normal.empty:
        raise ValueError(
            "No normal-only runs found. Generate baseline data with "
            "`opspilot simulate --virtual --normal-only --hours 24 --seed 11` "
            "and a second seed for a held-out validation run."
        )
    train_frame, validation_frame, split = _split_normal_runs(normal)
    if train_frame.empty or validation_frame.empty:
        raise ValueError("Not enough normal windows to fit and calibrate detectors")

    selected = _select_detectors(detector, settings)
    data_hash = _hash_sources(
        tuple(path for path in dataset.metric_paths if _run_id_from_path(path) in normal_runs)
    )
    now = SystemClock().now().astimezone(UTC)
    timestamp_slug = now.strftime("%Y%m%d-%H%M%S")
    artifacts: list[TrainedArtifact] = []
    registry = DetectorRegistry(model_root)

    for name, model in selected.items():
        model.fit(train_frame)
        threshold = model.calibrate(validation_frame, settings.threshold_quantile)
        artifact_dir = model_root / name / f"{timestamp_slug}-{data_hash[:8]}"
        model_path = artifact_dir / "model.joblib"
        model.save(model_path)
        metadata = {
            "detector": name,
            "created_at": now.isoformat(),
            "data_sha256": data_hash,
            "train_run_ids": split["train_run_ids"],
            "validation_run_ids": split["validation_run_ids"],
            "split_strategy": split["strategy"],
            "train_rows": len(train_frame),
            "validation_rows": len(validation_frame),
            "feature_count": len(model.feature_columns_),
            "feature_columns": model.feature_columns_,
            "threshold": threshold,
            "threshold_quantile": settings.threshold_quantile,
            "parameters": _detector_parameters(model, settings),
            "training_history": getattr(model, "training_history_", []),
            "library_versions": _library_versions(),
            "git_commit": None,
        }
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "threshold.json").write_text(
            json.dumps(
                {"threshold": threshold, "quantile": settings.threshold_quantile},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (artifact_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        registry.publish(name, artifact_dir)
        artifacts.append(
            TrainedArtifact(
                name=name,
                threshold=threshold,
                artifact_dir=artifact_dir,
                train_rows=len(train_frame),
                validation_rows=len(validation_frame),
            )
        )
    return artifacts


def _normal_run_ids(dataset: SimulationDataset) -> set[str]:
    all_run_ids = set(dataset.metrics["run_id"].astype(str).unique())
    if dataset.faults.empty:
        return all_run_ids
    fault_run_ids = set(dataset.faults["run_id"].astype(str).unique())
    return all_run_ids - fault_run_ids


def _split_normal_runs(
    normal: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    run_ids = sorted(normal["run_id"].astype(str).unique())
    if len(run_ids) >= 2:
        validation_id = run_ids[-1]
        train_ids = run_ids[:-1]
        train = normal.loc[normal["run_id"].astype(str).isin(train_ids)].copy()
        validation = normal.loc[normal["run_id"].astype(str) == validation_id].copy()
        return train, validation, {
            "strategy": "held_out_run",
            "train_run_ids": train_ids,
            "validation_run_ids": [validation_id],
        }

    run_id = run_ids[0]
    times = normal["ts"].sort_values().drop_duplicates()
    if len(times) < 2:
        raise ValueError("A normal run needs at least two distinct feature timestamps")
    cutoff_index = max(1, min(len(times) - 1, int(len(times) * 0.8)))
    cutoff = times.iloc[cutoff_index]
    train = normal.loc[normal["ts"] < cutoff].copy()
    validation = normal.loc[normal["ts"] >= cutoff].copy()
    return train, validation, {
        "strategy": "chronological_holdout_single_run",
        "train_run_ids": [run_id],
        "validation_run_ids": [run_id],
    }


def _select_detectors(
    detector: str, settings: DetectionSettings
) -> dict[str, BaseDetector]:
    if detector == "ml":
        selected_names = sorted(SUPPORTED_DETECTORS)
    elif detector in SUPPORTED_DETECTORS:
        selected_names = [detector]
    else:
        raise ValueError(
            f"Unsupported detector '{detector}'. Choose 'ml', "
            f"{', '.join(sorted(SUPPORTED_DETECTORS))}."
        )
    models: dict[str, BaseDetector] = {}
    for name in selected_names:
        if name == RollingZScoreDetector.name:
            models[name] = RollingZScoreDetector()
        elif name == IsolationForestDetector.name:
            models[name] = IsolationForestDetector(
                n_estimators=settings.isolation_forest.n_estimators,
                contamination=settings.isolation_forest.contamination,
                random_state=settings.isolation_forest.random_state,
            )
        elif name == LSTMAutoencoderDetector.name:
            params = settings.lstm_autoencoder
            models[name] = LSTMAutoencoderDetector(
                sequence_length=params.sequence_length,
                hidden_size=params.hidden_size,
                latent_size=params.latent_size,
                epochs=params.epochs,
                batch_size=params.batch_size,
                learning_rate=params.learning_rate,
                patience=params.patience,
                seed=params.seed,
            )
    return models


def _hash_sources(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _run_id_from_path(path: Path) -> str:
    prefix = "simulation_"
    suffix = "_metrics.parquet"
    if path.name.startswith(prefix) and path.name.endswith(suffix):
        return path.name[len(prefix) : -len(suffix)]
    return path.stem


def _detector_parameters(model: BaseDetector, settings: DetectionSettings) -> dict[str, object]:
    if isinstance(model, IsolationForestDetector):
        return {
            "n_estimators": settings.isolation_forest.n_estimators,
            "contamination": settings.isolation_forest.contamination,
            "random_state": settings.isolation_forest.random_state,
        }
    if isinstance(model, LSTMAutoencoderDetector):
        return settings.lstm_autoencoder.model_dump()
    return {
        "window_seconds": settings.window_seconds,
        "stride_seconds": settings.stride_seconds,
        "baseline_seconds": settings.baseline_seconds,
    }


def _library_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package in ("numpy", "pandas", "scikit-learn", "SQLAlchemy", "torch", "drain3"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    return versions

