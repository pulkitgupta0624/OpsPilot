"""Sliding-window features with strictly past-only rolling baselines."""

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from opspilot.core.errors import OpsPilotError

METRIC_COLUMNS: Final[tuple[str, ...]] = (
    "request_rate_per_s",
    "error_rate",
    "latency_ms_p50",
    "latency_ms_p95",
    "latency_ms_p99",
    "cpu_pct",
    "memory_mb",
    "db_pool_in_use",
    "db_pool_size",
    "queue_depth",
    "disk_used_pct",
    "restarts_total",
)
META_COLUMNS: Final[tuple[str, ...]] = ("run_id", "service", "ts", "app_version")


@dataclass(frozen=True)
class WindowConfig:
    """Temporal feature settings; defaults match the project blueprint."""

    window_seconds: int = 60
    stride_seconds: int = 10
    baseline_seconds: int = 1_800

    def __post_init__(self) -> None:
        if min(self.window_seconds, self.stride_seconds, self.baseline_seconds) <= 0:
            raise ValueError("Window and baseline durations must be positive")
        if self.stride_seconds > self.window_seconds:
            raise ValueError("stride_seconds cannot exceed window_seconds")


def build_feature_windows(metrics: pd.DataFrame, config: WindowConfig) -> pd.DataFrame:
    """Return one feature row per service/run/stride using only data at or before its time.

    The rolling baseline is shifted by one raw observation, so the row at time ``t`` can
    never use the sample at ``t`` or any future sample to define its baseline.
    """
    required = {"ts", "service", *METRIC_COLUMNS}
    missing = sorted(required - set(metrics.columns))
    if missing:
        raise ValueError(f"Metrics data is missing required columns: {', '.join(missing)}")
    if metrics.empty:
        return pd.DataFrame(columns=["run_id", "service", "ts"])

    data = metrics.copy()
    data["ts"] = pd.to_datetime(data["ts"], utc=True)
    if "run_id" not in data:
        data["run_id"] = "unknown"
    data = data.sort_values(["run_id", "service", "ts"], kind="stable")
    windows: list[pd.DataFrame] = []

    for (run_id, service), group in data.groupby(["run_id", "service"], sort=False):
        group = group.reset_index(drop=True)
        deltas = group["ts"].diff().dt.total_seconds().dropna()
        sample_seconds = float(deltas.median()) if not deltas.empty else config.stride_seconds
        if not np.isfinite(sample_seconds) or sample_seconds <= 0:
            raise OpsPilotError(f"Invalid sample cadence for run={run_id}, service={service}")
        window_samples = max(2, int(round(config.window_seconds / sample_seconds)) + 1)
        stride_samples = max(1, int(round(config.stride_seconds / sample_seconds)))
        baseline_samples = max(2, int(round(config.baseline_seconds / sample_seconds)))
        feature_data: dict[str, pd.Series] = {}

        for metric in METRIC_COLUMNS:
            values = pd.to_numeric(group[metric], errors="coerce").astype(float)
            rolling = values.rolling(window_samples, min_periods=window_samples)
            feature_data[f"{metric}__mean"] = rolling.mean()
            feature_data[f"{metric}__std"] = rolling.std(ddof=0)
            feature_data[f"{metric}__min"] = rolling.min()
            feature_data[f"{metric}__max"] = rolling.max()
            feature_data[f"{metric}__last"] = values
            feature_data[f"{metric}__slope"] = rolling.apply(
                _linear_slope, raw=True
            )
            feature_data[f"{metric}__ewma"] = values.ewm(
                span=window_samples, adjust=False, min_periods=window_samples
            ).mean()
            feature_data[f"{metric}__rate_of_change"] = (
                values - values.shift(window_samples - 1)
            ) / max(config.window_seconds, sample_seconds)
            feature_data[f"{metric}__p95"] = rolling.quantile(0.95)

            baseline = values.shift(1).rolling(
                baseline_samples, min_periods=baseline_samples
            )
            baseline_mean = baseline.mean()
            baseline_std = baseline.std(ddof=0).replace(0.0, np.nan)
            feature_data[f"{metric}__zscore"] = (values - baseline_mean) / baseline_std

        feature_frame = pd.DataFrame(feature_data)
        feature_frame["latency_error_interaction"] = (
            feature_frame["latency_ms_p95__mean"] * feature_frame["error_rate__mean"]
        )
        feature_frame["db_pool_saturation"] = (
            feature_frame["db_pool_in_use__mean"]
            / feature_frame["db_pool_size__mean"].replace(0.0, np.nan)
        )
        feature_frame["queue_growth"] = feature_frame["queue_depth__rate_of_change"]
        selected = np.arange(window_samples - 1, len(group), stride_samples)
        feature_frame = feature_frame.iloc[selected].reset_index(drop=True)
        metadata_columns = [column for column in META_COLUMNS if column in group.columns]
        metadata = group.iloc[selected][metadata_columns].reset_index(drop=True)
        result = pd.concat([metadata, feature_frame], axis=1)
        result["run_id"] = run_id
        result["service"] = service
        numeric_features = [column for column in feature_frame if column not in META_COLUMNS]
        result[numeric_features] = (
            result[numeric_features]
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
        )
        windows.append(result)

    if not windows:
        return pd.DataFrame(columns=["run_id", "service", "ts"])
    return (
        pd.concat(windows, ignore_index=True)
        .sort_values(["run_id", "service", "ts"], kind="stable")
        .reset_index(drop=True)
    )


def numeric_feature_columns(frame: pd.DataFrame) -> list[str]:
    """Select stable numeric feature columns, excluding identity and time fields."""
    excluded = set(META_COLUMNS)
    return [
        column
        for column in frame.select_dtypes(include=[np.number]).columns
        if column not in excluded
    ]


def _linear_slope(values: np.ndarray) -> float:
    """Compute an OLS slope for one fixed-size trailing window."""
    if values.size < 2 or not np.isfinite(values).all():
        return 0.0
    x = np.arange(values.size, dtype=float)
    x_centered = x - x.mean()
    denominator = float(np.dot(x_centered, x_centered))
    if denominator == 0.0:
        return 0.0
    y_centered = values - values.mean()
    return float(np.dot(x_centered, y_centered) / denominator)

