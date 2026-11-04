"""Append-only JSONL audit records for agent decisions and tool activity."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class JsonlAuditLog:
    """Write one durable JSON object per event; no update or delete API is exposed."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, incident_id: str, event: str, details: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "incident_id": incident_id,
            "event": event,
            "details": details,
        }
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def cooldown_active(self, service: str, action: str, cooldown_seconds: int) -> bool:
        """Check prior real simulator actions without mutating the append-only audit file."""
        if cooldown_seconds <= 0 or not self._path.is_file():
            return False
        cutoff = datetime.now(UTC) - timedelta(seconds=cooldown_seconds)
        try:
            records = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            # If audit history cannot be read, policy fails closed on repeat actions.
            return True
        for line in reversed(records):
            try:
                record = json.loads(line)
                details = record.get("details", {})
                if record.get("event") != "action_execution":
                    continue
                if details.get("dry_run") or details.get("service") != service:
                    continue
                if details.get("action") != action:
                    continue
                recorded_at = datetime.fromisoformat(str(record["ts"]))
                if recorded_at.tzinfo is None:
                    recorded_at = recorded_at.replace(tzinfo=UTC)
                return recorded_at >= cutoff
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return False

