"""Lightweight, versioned detector artifact registry."""

import json
from pathlib import Path
from typing import Any

from opspilot.detection.models.base import BaseDetector
from opspilot.detection.models.isolation_forest import IsolationForestDetector
from opspilot.detection.models.lstm_autoencoder import LSTMAutoencoderDetector
from opspilot.detection.models.zscore import RollingZScoreDetector

DETECTOR_CLASSES = {
    RollingZScoreDetector.name: RollingZScoreDetector,
    IsolationForestDetector.name: IsolationForestDetector,
    LSTMAutoencoderDetector.name: LSTMAutoencoderDetector,
}


class DetectorRegistry:
    """Publish immutable versioned artifacts and point a small JSON alias at latest."""

    def __init__(self, model_root: Path = Path("data/models")) -> None:
        self.model_root = model_root
        self.index_path = model_root / "registry.json"

    def publish(self, name: str, version_dir: Path) -> None:
        registry = self._read_index()
        relative = version_dir.resolve().relative_to(self.model_root.resolve()).as_posix()
        registry[name] = {"latest": relative}
        self.model_root.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.index_path)

    def load_latest(self, name: str) -> BaseDetector:
        """Load a registered detector artifact by its stable name."""
        detector_class = DETECTOR_CLASSES.get(name)
        if detector_class is None:
            raise KeyError(f"Unknown detector registered in OpsPilot: {name}")
        registry = self._read_index()
        entry: Any = registry.get(name)
        if not isinstance(entry, dict) or not isinstance(entry.get("latest"), str):
            raise FileNotFoundError(f"No trained artifact registered for detector '{name}'")
        artifact_path = self.model_root / entry["latest"] / "model.joblib"
        return detector_class.load(artifact_path)

    def _read_index(self) -> dict[str, object]:
        if not self.index_path.exists():
            return {}
        raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid model registry file: {self.index_path}")
        return raw

