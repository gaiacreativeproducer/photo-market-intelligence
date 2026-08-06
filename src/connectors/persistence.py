"""Persistence for connector health, incidents, and repair proposals."""

from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import ConnectorError, ConnectorHealth, ConnectorStatus


HEALTH_FIELDS = (
    "connector_name", "source_type", "status", "checked_at", "last_success_at",
    "response_time_ms", "result_count", "consecutive_failures", "message",
)
INCIDENT_FIELDS = (
    "incident_id", "connector_name", "occurred_at", "error_type", "severity",
    "message", "retry_attempted", "resolved", "resolved_at", "proposed_action",
)


def _iso(value: Optional[datetime]) -> str:
    return value.isoformat() if value else ""


class OperationalStore:
    def __init__(self, data_directory: Path) -> None:
        self.data_directory = data_directory
        self.health_path = data_directory / "connector_health.csv"
        self.incidents_path = data_directory / "connector_incidents.csv"
        self.repair_path = data_directory / "repair_proposals.json"
        data_directory.mkdir(parents=True, exist_ok=True)
        self._ensure_csv(self.health_path, HEALTH_FIELDS)
        self._ensure_csv(self.incidents_path, INCIDENT_FIELDS)
        if not self.repair_path.exists():
            self.repair_path.write_text("[]\n", encoding="utf-8")

    @staticmethod
    def _ensure_csv(path: Path, fields: Tuple[str, ...]) -> None:
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as output:
                csv.writer(output).writerow(fields)

    def append_health(self, health: ConnectorHealth) -> None:
        with self.health_path.open("a", newline="", encoding="utf-8") as output:
            csv.DictWriter(output, fieldnames=HEALTH_FIELDS).writerow(
                {
                    "connector_name": health.connector_name,
                    "source_type": health.source_type,
                    "status": health.status.value,
                    "checked_at": _iso(health.checked_at),
                    "last_success_at": _iso(health.last_success_at),
                    "response_time_ms": health.response_time_ms,
                    "result_count": health.result_count,
                    "consecutive_failures": health.consecutive_failures,
                    "message": health.message,
                }
            )

    def latest_health(self, connector_name: str) -> Optional[Dict[str, str]]:
        latest = None
        with self.health_path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                if row["connector_name"].casefold() == connector_name.casefold():
                    latest = row
        return latest

    def record_problem(
        self,
        connector_name: str,
        error: ConnectorError,
        retry_attempted: bool,
    ) -> Tuple[Dict[str, str], bool]:
        rows = self._incident_rows()
        unresolved = [
            row for row in rows
            if row["connector_name"].casefold() == connector_name.casefold()
            and row["resolved"].casefold() != "true"
        ]
        current = unresolved[-1] if unresolved else None
        severity_rank = {"warning": 1, "error": 2, "critical": 3}
        needs_new = current is None
        if current is not None:
            needs_new = (
                current["error_type"] != error.error_type
                or severity_rank.get(error.severity, 0)
                > severity_rank.get(current["severity"], 0)
            )

        if needs_new:
            if current is not None:
                current["resolved"] = "true"
                current["resolved_at"] = datetime.now(timezone.utc).isoformat()
            incident = {
                "incident_id": str(uuid.uuid4()),
                "connector_name": connector_name,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "error_type": error.error_type,
                "severity": error.severity,
                "message": error.message,
                "retry_attempted": str(retry_attempted).lower(),
                "resolved": "false",
                "resolved_at": "",
                "proposed_action": error.proposed_action,
            }
            rows.append(incident)
        else:
            incident = current
            incident["message"] = error.message
            incident["retry_attempted"] = str(retry_attempted).lower()
            incident["proposed_action"] = error.proposed_action

        self._write_incidents(rows)
        return incident, needs_new

    def resolve_problems(self, connector_name: str, resolved_at: datetime) -> None:
        rows = self._incident_rows()
        changed = False
        for row in rows:
            if (
                row["connector_name"].casefold() == connector_name.casefold()
                and row["resolved"].casefold() != "true"
            ):
                row["resolved"] = "true"
                row["resolved_at"] = resolved_at.isoformat()
                changed = True
        if changed:
            self._write_incidents(rows)

    def write_repair_proposal(
        self, connector_name: str, incident: Dict[str, str], error: ConnectorError
    ) -> None:
        try:
            proposals = json.loads(self.repair_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            proposals = []
        proposal = {
            "connector_name": connector_name,
            "incident_id": incident["incident_id"],
            "observed_error": error.message,
            "probable_cause": self._probable_cause(error.error_type),
            "suggested_checks": [error.proposed_action],
            "repair_status": "proposed",
        }
        proposals = [
            item for item in proposals if item.get("connector_name") != connector_name
        ]
        proposals.append(proposal)
        self.repair_path.write_text(
            json.dumps(proposals, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _probable_cause(error_type: str) -> str:
        return {
            "authentication": "Credentials are missing, expired, or unauthorized.",
            "timeout": "The source was unavailable or exceeded its timeout.",
            "network": "A temporary network failure interrupted the connector.",
            "malformed_data": "The source response no longer matches the expected schema.",
        }.get(error_type, "The connector raised an unexpected operational error.")

    def _incident_rows(self) -> List[Dict[str, str]]:
        with self.incidents_path.open(newline="", encoding="utf-8") as source:
            return list(csv.DictReader(source))

    def _write_incidents(self, rows: List[Dict[str, str]]) -> None:
        with self.incidents_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=INCIDENT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
