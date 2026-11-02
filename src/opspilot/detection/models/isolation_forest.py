"""Isolation Forest detector fitted only on normal windows."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from opspilot.detection.models.base import BaseDetector
from opspilot.domain.models.alert import SuspectFeature


class IsolationForestDetector(BaseDetector):
    """Standardized Isolation Forest with a validation-normal score threshold."""

    name = "isolation_forest"

    def __init__(
        self,
        *,
        n_estimators: int = 200,
        contamination: str | float = "auto",
        random_state: int = 42,
        top_k: int = 5,
    ) -> None:
        super().__init__(top_k=top_k)
        self.n_estimators = n_estimators
        self.contamination = contamination
        self.random_state = random_state
        self.scaler_: StandardScaler | None = None
        self.model_: IsolationForest | None = None
        self.normal_median_: pd.Series | None = None
        self.normal_scale_: pd.Series | None = None

    def fit(self, x_normal: pd.DataFrame) -> "IsolationForestDetector":
        self.feature_columns_ = self.select_features(x_normal)
        matrix = _finite_matrix(x_normal, self.feature_columns_)
        self.scaler_ = StandardScaler()
        standardized = self.scaler_.fit_transform(matrix)
        self.model_ = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_state,
            n_jobs=-1,
        )
        self.model_.fit(standardized)
        self.normal_median_ = x_normal[self.feature_columns_].median()
        iqr = x_normal[self.feature_columns_].quantile(0.75) - x_normal[
            self.feature_columns_
        ].quantile(0.25)
        self.normal_scale_ = iqr.where(iqr > 1e-9, 1.0)
        return self

    def score(self, x: pd.DataFrame) -> np.ndarray:
        model, scaler = self._require_model()
        matrix = _finite_matrix(x, self.feature_columns_)
        return -model.decision_function(scaler.transform(matrix))

    def explain(self, x: pd.DataFrame) -> list[list[SuspectFeature]]:
        columns = self.require_fitted()
        if self.normal_median_ is None or self.normal_scale_ is None:
            raise RuntimeError("Isolation Forest must be fitted before explanation")
        matrix = _finite_matrix(x, columns)
        deviation = (matrix - self.normal_median_.to_numpy()) / self.normal_scale_.to_numpy()
        explanations: list[list[SuspectFeature]] = []
        for values, row in zip(deviation, matrix, strict=True):
            order = np.argsort(np.abs(values))[::-1][: self.top_k]
            explanations.append(
                [
                    SuspectFeature(
                        name=columns[index],
                        value=float(row[index]),
                        contribution=float(abs(values[index])),
                    )
                    for index in order
                ]
            )
        return explanations

    def save(self, path: Path) -> None:
        self._require_model()
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "IsolationForestDetector":
        detector = joblib.load(path)
        if not isinstance(detector, cls):
            raise TypeError(f"Artifact at {path} is not a {cls.__name__}")
        return detector

    def _require_model(self) -> tuple[IsolationForest, StandardScaler]:
        if self.model_ is None or self.scaler_ is None:
            raise RuntimeError(f"{self.name} must be fitted before scoring")
        self.require_fitted()
        return self.model_, self.scaler_


def _finite_matrix(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"Feature frame is missing columns: {sorted(missing)}")
    values = frame[columns].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return values.to_numpy(dtype=float)

