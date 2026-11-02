"""Event-level detection metrics and N-consecutive-window alert grouping."""

from dataclasses import dataclass
from datetime import timedelta
from statistics import median

import pandas as pd


@dataclass(frozen=True)
class FaultInterval:
    run_id: str
    service: str
    fault_type: str
    start: pd.Timestamp
    end: pd.Timestamp


@dataclass(frozen=True)
class AlertEvent:
    run_id: str
    service: str
    started_at: pd.Timestamp


def consecutive_alerts(
    scores: pd.DataFrame,
    *,
    threshold: float,
    consecutive_windows: int,
) -> pd.DataFrame:
    """Group adjacent above-threshold windows into one alert start per episode."""
    if consecutive_windows < 1:
        raise ValueError("consecutive_windows must be at least one")
    required = {"run_id", "service", "ts", "score"}
    missing = required - set(scores.columns)
    if missing:
        raise ValueError(f"Score frame is missing columns: {sorted(missing)}")
    alerts: list[dict[str, object]] = []
    for (run_id, service), group in scores.groupby(["run_id", "service"], sort=False):
        group = group.sort_values("ts", kind="stable").reset_index(drop=True)
        streak_length = 0
        in_episode = False
        deltas = group["ts"].diff().dt.total_seconds().dropna()
        expected_stride = float(deltas.median()) if not deltas.empty else None
        previous_time: pd.Timestamp | None = None
        for _, row in group.iterrows():
            timestamp = pd.Timestamp(row["ts"])
            if (
                previous_time is not None
                and expected_stride is not None
                and (timestamp - previous_time).total_seconds() > expected_stride * 1.5
            ):
                streak_length = 0
                in_episode = False
            above = float(row["score"]) >= threshold
            if above:
                streak_length += 1
                if streak_length >= consecutive_windows and not in_episode:
                    alerts.append(
                        {
                            "run_id": str(run_id),
                            "service": str(service),
                            "ts": timestamp,
                        }
                    )
                    in_episode = True
            else:
                streak_length = 0
                in_episode = False
            previous_time = timestamp
    return pd.DataFrame.from_records(alerts, columns=["run_id", "service", "ts"])


def event_level_metrics(
    faults: pd.DataFrame,
    alerts: pd.DataFrame,
    *,
    grace_seconds: int = 30,
    simulated_days: float = 1.0,
) -> dict[str, float | int]:
    """Compute event precision/recall/F1, median detection delay, and false alarms/day."""
    if simulated_days <= 0:
        raise ValueError("simulated_days must be positive")
    normalized_faults = _normalize_faults(faults)
    normalized_alerts = _normalize_alerts(alerts)
    delays: list[float] = []
    detected = 0
    available_alerts = set(normalized_alerts.index)

    ordered_faults = normalized_faults.sort_values(
        ["run_id", "service", "start"], kind="stable"
    )
    for _, fault in ordered_faults.iterrows():
        eligible = normalized_alerts.loc[
            normalized_alerts.index.isin(available_alerts)
            & (normalized_alerts["run_id"] == fault["run_id"])
            & (normalized_alerts["service"] == fault["service"])
            & (normalized_alerts["ts"] >= fault["start"])
            & (
                normalized_alerts["ts"]
                <= fault["end"] + timedelta(seconds=grace_seconds)
            )
        ]
        if not eligible.empty:
            detected += 1
            first_index = eligible["ts"].idxmin()
            available_alerts.remove(int(first_index))
            delays.append(
                float((normalized_alerts.loc[first_index, "ts"] - fault["start"]).total_seconds())
            )

    false_alarms = len(available_alerts)
    recall = detected / len(normalized_faults) if len(normalized_faults) else 0.0
    precision = detected / (detected + false_alarms) if detected + false_alarms else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "fault_events": int(len(normalized_faults)),
        "detected_events": detected,
        "false_alarms": false_alarms,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "median_detection_delay_s": median(delays) if delays else float("nan"),
        "false_alarms_per_day": false_alarms / simulated_days,
    }


def _normalize_faults(faults: pd.DataFrame) -> pd.DataFrame:
    columns = ["run_id", "service", "fault_type", "start", "end"]
    if faults.empty:
        return pd.DataFrame(columns=columns)
    normalized = faults[columns].copy()
    normalized["start"] = pd.to_datetime(normalized["start"], utc=True)
    normalized["end"] = pd.to_datetime(normalized["end"], utc=True)
    return normalized


def _normalize_alerts(alerts: pd.DataFrame) -> pd.DataFrame:
    columns = ["run_id", "service", "ts"]
    if alerts.empty:
        return pd.DataFrame(columns=columns)
    normalized = alerts[columns].copy().reset_index(drop=True)
    normalized["ts"] = pd.to_datetime(normalized["ts"], utc=True)
    return normalized

