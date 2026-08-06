"""Strict atomic persistence for local notifications and preferences."""
from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import asdict, fields, replace
from datetime import datetime
from pathlib import Path
from typing import List

from .models import (
    DeliveryStatus, DigestMode, Notification, NotificationPreference,
    NotificationType, Severity,
)

FIELDS = tuple(item.name for item in fields(Notification))
PREFERENCE_KEYS = {item.name for item in fields(NotificationPreference)}


class NotificationStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "notifications.csv"
        self.preferences_path = directory / "notification_preferences.json"

    def load(self) -> List[Notification]:
        if not self.path.is_file():
            return []
        with self.path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise ValueError(f"{self.path}: invalid notification schema")
            return [_decode(row) for row in reader]

    def save(self, notifications) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".notifications.", dir=str(self.directory))
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                for item in notifications:
                    writer.writerow(_encode(item))
                handle.flush(); os.fsync(handle.fileno())
            os.replace(str(temporary), str(self.path))
        finally:
            if temporary.exists(): temporary.unlink()

    def update_state(self, notification_id: str, dismiss: bool = False) -> Notification:
        values = self.load()
        for index, item in enumerate(values):
            if item.notification_id == notification_id:
                values[index] = replace(item, read=True, dismissed=item.dismissed or dismiss)
                self.save(values)
                return values[index]
        raise KeyError("notification not found")

    def load_preferences(self) -> NotificationPreference:
        if not self.preferences_path.is_file():
            return NotificationPreference()
        data = json.loads(self.preferences_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != PREFERENCE_KEYS:
            raise ValueError(f"{self.preferences_path}: invalid preference schema")
        data["minimum_severity"] = Severity(data["minimum_severity"])
        data["digest_mode"] = DigestMode(data["digest_mode"])
        preference = NotificationPreference(**data)
        if not 0 <= preference.minimum_recognition_confidence <= 100:
            raise ValueError("minimum_recognition_confidence must be from 0 to 100")
        return preference


def _encode(item):
    value = asdict(item)
    for key in ("notification_type", "severity", "delivery_status"):
        value[key] = getattr(item, key).value
    value["created_at"] = item.created_at.isoformat()
    value["delivered_at"] = item.delivered_at.isoformat() if item.delivered_at else ""
    value["read"] = "true" if item.read else "false"
    value["dismissed"] = "true" if item.dismissed else "false"
    value["evidence"] = json.dumps(item.evidence, separators=(",", ":"), sort_keys=True)
    return value


def _decode(row):
    return Notification(
        row["notification_id"], NotificationType(row["notification_type"]),
        Severity(row["severity"]), row["title"], row["message"],
        row["product_id"], row["listing_id"], row["source_id"],
        datetime.fromisoformat(row["created_at"]), row["read"] == "true",
        row["dismissed"] == "true", row["action_url"],
        json.loads(row["evidence"] or "{}"), row["deduplication_key"],
        DeliveryStatus(row["delivery_status"]),
        datetime.fromisoformat(row["delivered_at"]) if row["delivered_at"] else None,
        int(row["delivery_attempts"]), row["delivery_message"],
    )


def preference_json(preference: NotificationPreference):
    value = asdict(preference)
    value["minimum_severity"] = preference.minimum_severity.value
    value["digest_mode"] = preference.digest_mode.value
    return value
