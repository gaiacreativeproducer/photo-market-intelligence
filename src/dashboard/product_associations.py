"""Explicit user product associations stored separately from radar recognition."""

from __future__ import annotations

import csv
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence

from catalog import Product
from radar.persistence import RadarStore


FIELDS = ("listing_id", "product_id", "manual_assignment_at", "manual_assignment_source")


@dataclass(frozen=True)
class ManualProductAssignment:
    listing_id: str
    product_id: str
    manual_assignment_at: datetime
    manual_assignment_source: str = "USER"


class ManualProductAssignmentStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "manual_product_assignments.csv"

    def load(self) -> Dict[str, ManualProductAssignment]:
        if not self.path.is_file():
            return {}
        with self.path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise ValueError(f"{self.path}: invalid manual product assignment header")
            values: Dict[str, ManualProductAssignment] = {}
            for row_number, row in enumerate(reader, start=2):
                listing_id = row["listing_id"].strip()
                product_id = row["product_id"].strip()
                source = row["manual_assignment_source"].strip()
                try:
                    assigned_at = datetime.fromisoformat(row["manual_assignment_at"])
                except ValueError as error:
                    raise ValueError(f"{self.path}: row {row_number}: manual_assignment_at is invalid") from error
                if not listing_id or not product_id or source != "USER" or assigned_at.tzinfo is None:
                    raise ValueError(f"{self.path}: row {row_number}: invalid manual product assignment")
                if listing_id in values:
                    raise ValueError(f"{self.path}: row {row_number}: duplicate listing_id")
                values[listing_id] = ManualProductAssignment(listing_id, product_id, assigned_at, source)
            return values

    def save(self, values: Sequence[ManualProductAssignment]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.directory))
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                for value in sorted(values, key=lambda item: item.listing_id):
                    writer.writerow({
                        "listing_id": value.listing_id,
                        "product_id": value.product_id,
                        "manual_assignment_at": value.manual_assignment_at.isoformat(),
                        "manual_assignment_source": value.manual_assignment_source,
                    })
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temporary), str(self.path))
        finally:
            if temporary.exists():
                temporary.unlink()


class ManualProductAssociationService:
    def __init__(
        self, store: ManualProductAssignmentStore, radar_store: RadarStore,
        products: Sequence[Product], now=None,
    ) -> None:
        self.store = store
        self.radar_store = radar_store
        self.products = {item.id: item for item in products}
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()

    def assign(
        self, listing_id: str, product_id: Optional[str]
    ) -> Optional[ManualProductAssignment]:
        if not any(item.listing_id == listing_id for item in self.radar_store.load_listings()):
            raise KeyError("listing")
        if product_id is not None and product_id not in self.products:
            raise KeyError("product")
        with self._lock:
            values = self.store.load()
            if product_id is None:
                values.pop(listing_id, None)
                self.store.save(list(values.values()))
                return None
            assignment = ManualProductAssignment(listing_id, product_id, self.now(), "USER")
            values[listing_id] = assignment
            self.store.save(list(values.values()))
            return assignment
