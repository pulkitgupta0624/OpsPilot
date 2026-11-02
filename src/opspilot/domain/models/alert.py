"""Typed explainability records emitted by anomaly detectors."""

from pydantic import BaseModel, ConfigDict


class SuspectFeature(BaseModel):
    """A feature contribution that explains an anomaly score."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: float
    contribution: float

