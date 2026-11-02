"""Common detector interface and threshold calibration behavior."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd

from opspilot.detection.features.windowing import numeric_feature_columns
from opspilot.domain.models.alert import SuspectFeature


class BaseDetector(ABC):
    """A detector whose score increases with anomaly likelihood."""

    name: ClassVar[str]

    def __init__(self, *, top_k: int = 5) -> None:
        self.top_k = top_k
        self.threshold_: float | None = None
        self.feature_columns_: list[str] = []

    @abstractmethod
    def fit(self, x_normal: pd.DataFrame) -> "BaseDetector": ...

    @abstractmethod
    def score(self, x: pd.DataFrame) -> np.ndarray: ...

    @abstractmethod
    def explain(self, x: pd.DataFrame) -> list[list[SuspectFeature]]: ...

    def calibrate(self, x_validation_normal: pd.DataFrame, quantile: float = 0.995) -> float:
        """Set a score cutoff from held-out normal validation windows."""
        if not 0.5 < quantile < 1.0:
            raise ValueError("quantile must be between 0.5 and 1.0")
        scores = self.score(x_validation_normal)
        scores = scores[np.isfinite(scores)]
        if scores.size == 0:
            raise ValueError("Cannot calibrate a threshold on an empty validation set")
        self.threshold_ = float(np.quantile(scores, quantile))
        return self.threshold_

    def require_fitted(self) -> list[str]:
        if not self.feature_columns_:
            raise RuntimeError(f"{self.name} must be fitted before scoring")
        return self.feature_columns_

    @staticmethod
    def select_features(frame: pd.DataFrame) -> list[str]:
        columns = numeric_feature_columns(frame)
        if not columns:
            raise ValueError("No numeric feature columns found")
        return columns

    @abstractmethod
    def save(self, path: Path) -> None: ...

