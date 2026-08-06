"""Tests for the minimal Photo Market Intelligence application."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import main


class MainTests(unittest.TestCase):
    def test_application_runs_successfully(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "src" / "main.py")],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            "Photo Market Intelligence\n"
            "Status: OK\n"
            "Products: 0\n"
            "Wishlist: 0\n"
            "Listings: 0\n"
            "System ready.\n",
        )
        self.assertEqual(result.stderr, "")

    def test_counts_data_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_directory = root / "data"
            data_directory.mkdir()

            self.write_csv(data_directory / "products.csv", 2)
            self.write_csv(data_directory / "wishlist.csv", 1)
            self.write_csv(data_directory / "listings.csv", 3)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = main.run(root)

            self.assertEqual(exit_code, 0)
            self.assertIn("Products: 2", output.getvalue())
            self.assertIn("Wishlist: 1", output.getvalue())
            self.assertIn("Listings: 3", output.getvalue())

    def test_missing_file_produces_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_directory = root / "data"
            data_directory.mkdir()

            self.write_csv(data_directory / "products.csv", 0)
            self.write_csv(data_directory / "wishlist.csv", 0)

            error_output = StringIO()
            with redirect_stderr(error_output):
                exit_code = main.run(root)

            self.assertEqual(exit_code, 1)
            self.assertIn("required CSV file not found", error_output.getvalue())
            self.assertIn("listings.csv", error_output.getvalue())

    @staticmethod
    def write_csv(csv_path: Path, row_count: int) -> None:
        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["id"])
            for row_number in range(row_count):
                writer.writerow([row_number])


if __name__ == "__main__":
    unittest.main()
