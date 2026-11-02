"""Idempotent persistence for simulator ground-truth fault intervals."""

from collections.abc import Sequence

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from opspilot.domain.models.telemetry import GroundTruthRecord
from opspilot.ingestion.schema import ground_truth_faults


class PostgresGroundTruthStore:
    """Store fault labels alongside their generated simulation run."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def write(self, records: Sequence[GroundTruthRecord]) -> int:
        rows = [
            {
                "run_id": record.run_id,
                "fault_id": record.fault_id,
                "fault_type": record.fault_type.value,
                "service": record.service,
                "start_ts": record.start,
                "end_ts": record.end,
                "intensity": record.intensity,
                "correct_actions": [action.value for action in record.correct_actions],
                "acceptable_actions": [action.value for action in record.acceptable_actions],
            }
            for record in records
        ]
        if not rows:
            return 0
        statement = insert(ground_truth_faults).values(rows).on_conflict_do_nothing(
            index_elements=["run_id", "fault_id"]
        )
        with self._engine.begin() as connection:
            result = connection.execute(statement)
        return int(result.rowcount or 0)

