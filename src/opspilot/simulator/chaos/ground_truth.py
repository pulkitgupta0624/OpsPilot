"""JSONL persistence for simulator fault ground truth."""

from pathlib import Path
from typing import Iterable

from opspilot.domain.models.telemetry import GroundTruthRecord


class GroundTruthWriter:
    """Write one validated fault record per line, creating the parent directory."""

    def write(self, path: Path, records: Iterable[GroundTruthRecord]) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = [record.model_dump_json() for record in records]
        path.write_text("\n".join(serialized) + ("\n" if serialized else ""), encoding="utf-8")
        return len(serialized)

