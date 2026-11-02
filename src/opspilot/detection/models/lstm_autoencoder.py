"""CPU-friendly LSTM autoencoder for sequences of normal feature windows."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.preprocessing import StandardScaler
from torch import Tensor, nn
from torch.utils.data import DataLoader, Dataset

from opspilot.detection.models.base import BaseDetector
from opspilot.domain.models.alert import SuspectFeature


class WindowSequenceDataset(Dataset[Tensor]):
    """Tensor dataset for fixed-length windows grouped by run and service."""

    def __init__(self, sequences: np.ndarray) -> None:
        self._sequences = torch.as_tensor(sequences, dtype=torch.float32)

    def __len__(self) -> int:
        return int(self._sequences.shape[0])

    def __getitem__(self, index: int) -> Tensor:
        return self._sequences[index]


class LSTMAutoencoder(nn.Module):
    """Encode a feature sequence into a bottleneck and reconstruct its time steps."""

    def __init__(
        self,
        *,
        n_features: int,
        hidden_size: int,
        latent_size: int,
    ) -> None:
        super().__init__()
        self.encoder = nn.LSTM(n_features, hidden_size, batch_first=True)
        self.to_latent = nn.Linear(hidden_size, latent_size)
        self.from_latent = nn.Linear(latent_size, hidden_size)
        self.decoder = nn.LSTM(hidden_size, hidden_size, batch_first=True)
        self.output_layer = nn.Linear(hidden_size, n_features)

    def forward(self, values: Tensor) -> Tensor:
        _, (hidden, _) = self.encoder(values)
        latent = self.to_latent(hidden[-1])
        repeated = self.from_latent(latent).unsqueeze(1).expand(
            -1, values.size(1), -1
        )
        decoded, _ = self.decoder(repeated)
        return self.output_layer(decoded)


class LSTMAutoencoderDetector(BaseDetector):
    """Score each complete sequence by its normalized reconstruction error."""

    name = "lstm_autoencoder"

    def __init__(
        self,
        *,
        sequence_length: int = 6,
        hidden_size: int = 32,
        latent_size: int = 8,
        epochs: int = 20,
        batch_size: int = 256,
        learning_rate: float = 0.001,
        patience: int = 4,
        seed: int = 42,
        top_k: int = 5,
    ) -> None:
        super().__init__(top_k=top_k)
        self.sequence_length = sequence_length
        self.hidden_size = hidden_size
        self.latent_size = latent_size
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.patience = patience
        self.seed = seed
        self.scaler_: StandardScaler | None = None
        self.model_: LSTMAutoencoder | None = None
        self.training_history_: list[dict[str, float]] = []

    def fit(self, x_normal: pd.DataFrame) -> "LSTMAutoencoderDetector":
        self.feature_columns_ = self.select_features(x_normal)
        values = _finite_matrix(x_normal, self.feature_columns_)
        self.scaler_ = StandardScaler().fit(values)
        normalized = self.scaler_.transform(values)
        sequences, _ = _make_sequences(x_normal, normalized, self.sequence_length)
        if len(sequences) < 3:
            raise ValueError(
                "LSTM training needs at least three complete normal sequences; "
                "provide more normal windows or reduce sequence_length"
            )

        torch.manual_seed(self.seed)
        np.random.seed(self.seed)
        self.model_ = LSTMAutoencoder(
            n_features=len(self.feature_columns_),
            hidden_size=self.hidden_size,
            latent_size=self.latent_size,
        ).cpu()
        rng = np.random.default_rng(self.seed)
        order = rng.permutation(len(sequences))
        validation_size = max(1, int(round(len(order) * 0.1)))
        validation_indices = order[:validation_size]
        training_indices = order[validation_size:]
        training_data = WindowSequenceDataset(sequences[training_indices])
        validation_data = WindowSequenceDataset(sequences[validation_indices])
        generator = torch.Generator().manual_seed(self.seed)
        training_loader = DataLoader(
            training_data,
            batch_size=self.batch_size,
            shuffle=True,
            generator=generator,
        )
        validation_loader = DataLoader(
            validation_data,
            batch_size=self.batch_size,
            shuffle=False,
        )

        optimizer = torch.optim.Adam(self.model_.parameters(), lr=self.learning_rate)
        loss_function = nn.MSELoss()
        best_loss = float("inf")
        best_state: dict[str, Tensor] | None = None
        stale_epochs = 0
        self.training_history_ = []

        for epoch in range(self.epochs):
            self.model_.train()
            training_loss = _mean_loader_loss(
                self.model_, training_loader, loss_function, optimizer
            )
            self.model_.eval()
            with torch.no_grad():
                validation_loss = _mean_loader_loss(
                    self.model_, validation_loader, loss_function
                )
            self.training_history_.append(
                {
                    "epoch": float(epoch + 1),
                    "training_loss": training_loss,
                    "validation_loss": validation_loss,
                }
            )
            if validation_loss < best_loss:
                best_loss = validation_loss
                best_state = {
                    key: value.detach().clone()
                    for key, value in self.model_.state_dict().items()
                }
                stale_epochs = 0
            else:
                stale_epochs += 1
                if stale_epochs >= self.patience:
                    break

        if best_state is None:
            raise RuntimeError("LSTM training did not produce a validation checkpoint")
        self.model_.load_state_dict(best_state)
        self.model_.eval()
        return self

    def score(self, x: pd.DataFrame) -> np.ndarray:
        errors, end_positions = self._sequence_errors(x)
        scores = np.full(len(x), np.nan, dtype=float)
        if len(end_positions):
            scores[end_positions] = errors.mean(axis=1)
        return scores

    def explain(self, x: pd.DataFrame) -> list[list[SuspectFeature]]:
        errors, end_positions = self._sequence_errors(x)
        original_values = _finite_matrix(x, self.require_fitted())
        explanations: list[list[SuspectFeature]] = [[] for _ in range(len(x))]
        for feature_errors, position in zip(errors, end_positions, strict=True):
            ranking = np.argsort(feature_errors)[::-1][: self.top_k]
            explanations[int(position)] = [
                SuspectFeature(
                    name=self.feature_columns_[index],
                    value=float(original_values[position, index]),
                    contribution=float(feature_errors[index]),
                )
                for index in ranking
            ]
        return explanations

    def save(self, path: Path) -> None:
        if self.model_ is None or self.scaler_ is None:
            raise RuntimeError("LSTM detector must be fitted before saving")
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "LSTMAutoencoderDetector":
        detector = joblib.load(path)
        if not isinstance(detector, cls):
            raise TypeError(f"Artifact at {path} is not a {cls.__name__}")
        return detector

    def _sequence_errors(self, x: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        if self.model_ is None or self.scaler_ is None:
            raise RuntimeError("LSTM detector must be fitted before scoring")
        columns = self.require_fitted()
        values = _finite_matrix(x, columns)
        normalized = self.scaler_.transform(values)
        sequences, end_positions = _make_sequences(x, normalized, self.sequence_length)
        if not len(sequences):
            return np.empty((0, len(columns)), dtype=float), end_positions
        self.model_.eval()
        with torch.no_grad():
            source = torch.as_tensor(sequences, dtype=torch.float32)
            reconstruction = self.model_(source)
            feature_errors = (reconstruction - source).pow(2).mean(dim=1)
        return feature_errors.cpu().numpy(), end_positions


def _finite_matrix(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"Feature frame is missing columns: {sorted(missing)}")
    return (
        frame[columns]
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
        .to_numpy(dtype=float)
    )


def _make_sequences(
    frame: pd.DataFrame,
    values: np.ndarray,
    sequence_length: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build sliding sequences without crossing a run or service boundary."""
    working = frame.reset_index(drop=True).copy()
    working["_row_position"] = np.arange(len(working), dtype=int)
    identity_columns = [column for column in ("run_id", "service") if column in working]
    if not identity_columns:
        working["_group"] = "all"
        identity_columns = ["_group"]
    order_columns = [*identity_columns]
    if "ts" in working:
        order_columns.append("ts")
    working = working.sort_values(order_columns, kind="stable")

    sequences: list[np.ndarray] = []
    endings: list[int] = []
    for _, group in working.groupby(identity_columns, sort=False, dropna=False):
        positions = group["_row_position"].to_numpy(dtype=int)
        if len(positions) < sequence_length:
            continue
        for start in range(len(positions) - sequence_length + 1):
            sequence_positions = positions[start : start + sequence_length]
            sequences.append(values[sequence_positions])
            endings.append(int(sequence_positions[-1]))
    if not sequences:
        return (
            np.empty((0, sequence_length, values.shape[1]), dtype=float),
            np.empty(0, dtype=int),
        )
    return np.stack(sequences), np.asarray(endings, dtype=int)


def _mean_loader_loss(
    model: LSTMAutoencoder,
    loader: DataLoader[Tensor],
    loss_function: nn.Module,
    optimizer: torch.optim.Optimizer | None = None,
) -> float:
    total_loss = 0.0
    total_sequences = 0
    for batch in loader:
        if optimizer is not None:
            optimizer.zero_grad(set_to_none=True)
        reconstruction = model(batch)
        loss = loss_function(reconstruction, batch)
        if optimizer is not None:
            loss.backward()
            optimizer.step()
        count = int(batch.size(0))
        total_loss += float(loss.detach()) * count
        total_sequences += count
    return total_loss / max(total_sequences, 1)
