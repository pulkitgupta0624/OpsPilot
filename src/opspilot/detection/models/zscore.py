"""Interpretable rolling z-score baseline detector."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from opspilot.detection.models.base import BaseDetector
from opspilot.domain.models.alert import SuspectFeature


class RollingZScoreDetector(BaseDetector):
    """Score each window by its largest absolute past-only baseline z-score."""

    name = "rolling_zscore"

    def fit(self, x_normal: pd.DataFrame) -> "RollingZScoreDetector":
        self.feature_columns_ = [
            column for column in x_normal.columns if column.endswith("__zscore")
        ]
        if not self.feature_columns_:
            raise ValueError("Rolling z-score features are missing from the training frame")
        return self

    def score(self, x: pd.DataFrame) -> np.ndarray:
        columns = self.require_fitted()
        missing = set(columns) - set(x.columns)
        if missing:
            raise ValueError(f"Scoring frame is missing fitted features: {sorted(missing)}")
        return (
            x[columns]
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
            .abs()
            .max(axis=1)
            .to_numpy(dtype=float)
        )

    def explain(self, x: pd.DataFrame) -> list[list[SuspectFeature]]:
        columns = self.require_fitted()
        explanations: list[list[SuspectFeature]] = []
        for _, row in x[columns].iterrows():
            ordered = sorted(columns, key=lambda column: abs(float(row[column])), reverse=True)
            explanations.append(
                [
                    SuspectFeature(
                        name=column.removesuffix("__zscore"),
                        value=float(row[column]),
                        contribution=abs(float(row[column])),
                    )
                    for column in ordered[: self.top_k]
                ]
            )
        return explanations

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "RollingZScoreDetector":
        detector = joblib.load(path)
        if not isinstance(detector, cls):
            raise TypeError(f"Artifact at {path} is not a {cls.__name__}")
        return detector

