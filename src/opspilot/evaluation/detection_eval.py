"""Offline scoring and event-level comparison for registered detectors."""

from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

import pandas as pd

from opspilot.core.clock import SystemClock
from opspilot.detection.config import load_detection_settings
from opspilot.detection.features.windowing import WindowConfig, build_feature_windows
from opspilot.detection.registry import DetectorRegistry
from opspilot.evaluation.datasets import load_simulation_dataset
from opspilot.evaluation.detection_metrics import consecutive_alerts, event_level_metrics


@dataclass(frozen=True)
class DetectionEvaluation:
    """Paths and row counts for one detector comparison report."""

    csv_path: Path
    markdown_path: Path
    scores_path: Path
    result_rows: int


def evaluate_classical_detectors(
    *,
    data_root: Path = Path("data"),
    model_root: Path = Path("data/models"),
    config_path: Path = Path("configs/detection.yaml"),
    report_dir: Path = Path("evals/reports"),
) -> tuple[pd.DataFrame, DetectionEvaluation]:
    """Score every available run and report overall plus per-fault-type metrics."""
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
    if dataset.faults.empty:
        raise ValueError("No fault-injected evaluation runs found in the dataset")
    fault_run_ids = set(dataset.faults["run_id"].astype(str).unique())
    evaluation_features = features.loc[
        features["run_id"].astype(str).isin(fault_run_ids)
    ].copy()
    evaluation_faults = dataset.faults.loc[
        dataset.faults["run_id"].astype(str).isin(fault_run_ids)
    ].copy()
    evaluation_metrics = dataset.metrics.loc[
        dataset.metrics["run_id"].astype(str).isin(fault_run_ids)
    ].copy()
    simulated_days = _simulated_days(evaluation_metrics)
    registry = DetectorRegistry(model_root)
    all_rows: list[dict[str, object]] = []
    all_score_frames: list[pd.DataFrame] = []
    detector_names = ("rolling_zscore", "isolation_forest", "lstm_autoencoder")

    for detector_name in detector_names:
        model = registry.load_latest(detector_name)
        if model.threshold_ is None:
            raise ValueError(f"Detector '{detector_name}' has no calibrated threshold")
        score_frame = evaluation_features[["run_id", "service", "ts"]].copy()
        score_frame["score"] = model.score(evaluation_features)
        score_frame["detector"] = detector_name
        all_score_frames.append(score_frame)
        alerts = consecutive_alerts(
            score_frame[["run_id", "service", "ts", "score"]],
            threshold=model.threshold_,
            consecutive_windows=settings.consecutive_windows,
        )
        overall = event_level_metrics(
            evaluation_faults,
            alerts,
            grace_seconds=settings.fault_grace_seconds,
            simulated_days=simulated_days,
        )
        all_rows.append({"detector": detector_name, "fault_type": "overall", **overall})

        if not evaluation_faults.empty:
            for fault_type in sorted(evaluation_faults["fault_type"].astype(str).unique()):
                type_faults = evaluation_faults.loc[
                    evaluation_faults["fault_type"].astype(str) == fault_type
                ]
                type_metrics = event_level_metrics(
                    type_faults,
                    alerts,
                    grace_seconds=settings.fault_grace_seconds,
                    simulated_days=simulated_days,
                )
                type_metrics["false_alarms"] = overall["false_alarms"]
                type_metrics["false_alarms_per_day"] = overall["false_alarms_per_day"]
                detected = int(type_metrics["detected_events"])
                false_alarms = int(type_metrics["false_alarms"])
                precision = detected / (detected + false_alarms) if detected + false_alarms else 0.0
                recall = float(type_metrics["recall"])
                type_metrics["precision"] = precision
                type_metrics["f1"] = (
                    2 * precision * recall / (precision + recall)
                    if precision + recall
                    else 0.0
                )
                all_rows.append(
                    {"detector": detector_name, "fault_type": fault_type, **type_metrics}
                )

    results = pd.DataFrame.from_records(all_rows)
    report_dir.mkdir(parents=True, exist_ok=True)
    now = SystemClock().now().astimezone(UTC)
    timestamp_slug = now.strftime("%Y%m%d-%H%M%S")
    csv_path = report_dir / f"detection_results_{timestamp_slug}.csv"
    markdown_path = report_dir / f"detection_results_{timestamp_slug}.md"
    scores_path = report_dir / f"detection_scores_{timestamp_slug}.parquet"
    results.to_csv(csv_path, index=False)
    pd.concat(all_score_frames, ignore_index=True).to_parquet(
        scores_path, index=False, compression="zstd"
    )
    markdown_path.write_text(_render_markdown(results, now.isoformat()), encoding="utf-8")
    return results, DetectionEvaluation(
        csv_path=csv_path,
        markdown_path=markdown_path,
        scores_path=scores_path,
        result_rows=len(results),
    )


def _simulated_days(metrics: pd.DataFrame) -> float:
    durations = metrics.groupby("run_id")["ts"].agg(["min", "max"])
    seconds = (durations["max"] - durations["min"]).dt.total_seconds().sum()
    return max(float(seconds) / 86_400.0, 1.0 / 24.0)


def _render_markdown(results: pd.DataFrame, created_at: str) -> str:
    columns = [
        "detector",
        "fault_type",
        "fault_events",
        "detected_events",
        "false_alarms",
        "precision",
        "recall",
        "f1",
        "median_detection_delay_s",
        "false_alarms_per_day",
    ]
    display = results[columns].copy()
    for column in ("precision", "recall", "f1", "false_alarms_per_day"):
        display[column] = display[column].map(lambda value: f"{float(value):.3f}")
    display["median_detection_delay_s"] = display["median_detection_delay_s"].map(
        lambda value: "n/a" if pd.isna(value) else f"{float(value):.1f}"
    )
    lines = [
        "# Detection evaluation",
        "",
        f"Generated at: `{created_at}`",
        "",
        "Per-fault rows use the global false-alarm count for the full evaluation set.",
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in display.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    lines.append("")
    return "\n".join(lines)

