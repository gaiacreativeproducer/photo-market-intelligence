"""Persistence tests for transparent manual product associations."""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dashboard.product_associations import ManualProductAssignment, ManualProductAssignmentStore


class ManualProductAssignmentStoreTests(unittest.TestCase):
    def test_round_trip_and_atomic_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ManualProductAssignmentStore(Path(directory))
            assigned_at = datetime(2026, 8, 7, tzinfo=timezone.utc)
            value = ManualProductAssignment("listing", "sony-alpha-a7-iv", assigned_at)
            store.save([value])
            self.assertEqual(store.load(), {"listing": value})
            store.save([])
            self.assertEqual(store.load(), {})

    def test_python_39(self) -> None:
        ast.parse((ROOT / "src/dashboard/product_associations.py").read_text(), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
