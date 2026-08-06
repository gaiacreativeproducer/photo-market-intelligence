"""Tests for the Photo Market Intelligence application entry point."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import main
from catalog import (
    MANUFACTURER_FIELDS,
    MOUNT_FIELDS,
    PRODUCT_ALIAS_FIELDS,
    PRODUCT_FIELDS,
)


class MainTests(unittest.TestCase):
    def test_application_runs_successfully(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main.run(
                    PROJECT_ROOT, Path(temporary_directory)
                )

        self.assertEqual(exit_code, 0)
        application_output = output.getvalue()
        for expected in (
            "Photo Market Intelligence\n",
            "Status: OK\n",
            "Products: 34\n",
            "Product aliases: 54\n",
            "Manufacturers: 13\n",
            "Mounts: 10\n",
            "Wishlist: 0\n",
            "Listings: 0\n",
            "Connector: mock-marketplace\n",
            "Connector health: HEALTHY\n",
            "Connector listings: 1\n",
            "Connector incidents: 0\n",
            "Decision example: clean used versus new\n",
            "Decision example: low price with cracked lens\n",
            "Extracted shutter count: 60000\n",
            "Invoice available: True\n",
            "Original box available: True\n",
            "Description analysis confidence:",
            "Recognition example: single product\n",
            "Recognized primary product: Sony Alpha A7 IV\n",
            "Recognition example: kit\n",
            "Recognition example: first generation\n",
            "Recognized primary product: Sigma 24-70mm f/2.8 DG DN Art\n",
            "Market example: Sony A7 IV used market\n",
            "Market median: 1140.00\n",
            "Market mean: 1140.00\n",
            "Market outliers: 1\n",
            "Market confidence: 70\n",
            "Listing quality average: 100.00\n",
            "Estimated 12-month depreciation: Unavailable\n",
            "Ownership example: Sony A7 IV new versus used\n",
            "Ownership recommendation:",
            "a7-iv-new acquisition cost: 1595.00\n",
            "a7-iv-used acquisition cost: 1200.00\n",
            "Break-even target used price:",
            "Ownership example: cracked lens new versus used\n",
            "Ownership recommendation: MANUAL_REVIEW\n",
            "System ready.\n",
        ):
            self.assertIn(expected, application_output)

    def test_counts_data_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_directory = root / "data"
            data_directory.mkdir()
            self.write_catalog(data_directory, product_count=2, alias_count=1)
            self.write_simple_csv(data_directory / "wishlist.csv", 1)
            self.write_simple_csv(data_directory / "listings.csv", 3)

            output = StringIO()
            with redirect_stdout(output):
                exit_code = main.run(root, data_directory)

            self.assertEqual(exit_code, 0)
            self.assertIn("Products: 2", output.getvalue())
            self.assertIn("Product aliases: 1", output.getvalue())
            self.assertIn("Manufacturers: 1", output.getvalue())
            self.assertIn("Mounts: 1", output.getvalue())
            self.assertIn("Wishlist: 1", output.getvalue())
            self.assertIn("Listings: 3", output.getvalue())

    def test_missing_file_produces_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_directory = root / "data"
            data_directory.mkdir()
            self.write_catalog(data_directory, product_count=0, alias_count=0)
            self.write_simple_csv(data_directory / "wishlist.csv", 0)

            error_output = StringIO()
            with redirect_stderr(error_output):
                exit_code = main.run(root)

            self.assertEqual(exit_code, 1)
            self.assertIn("required CSV file not found", error_output.getvalue())
            self.assertIn("listings.csv", error_output.getvalue())

    @classmethod
    def write_catalog(
        cls, data_directory: Path, product_count: int, alias_count: int
    ) -> None:
        cls.write_dict_csv(
            data_directory / "manufacturers.csv",
            MANUFACTURER_FIELDS,
            [{"id": "test", "name": "Test", "normalized_name": "test"}],
        )
        cls.write_dict_csv(
            data_directory / "mounts.csv",
            MOUNT_FIELDS,
            [{"id": "none", "name": "None", "mount_type": "Not applicable"}],
        )
        products = [
            {
                "id": f"product-{index}",
                "category": "Camera",
                "product_type": "Mirrorless",
                "brand": "Test",
                "model": f"Model {index}",
                "native_mount": "none",
            }
            for index in range(product_count)
        ]
        cls.write_dict_csv(
            data_directory / "products.csv", PRODUCT_FIELDS, products
        )
        aliases = [
            {
                "alias": f"alias {index}",
                "product_id": products[index % product_count]["id"],
                "alias_type": "common_name",
            }
            for index in range(alias_count)
        ] if product_count else []
        cls.write_dict_csv(
            data_directory / "product_aliases.csv", PRODUCT_ALIAS_FIELDS, aliases
        )

    @staticmethod
    def write_dict_csv(csv_path: Path, fields: Sequence[str], rows) -> None:
        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def write_simple_csv(csv_path: Path, row_count: int) -> None:
        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["id"])
            for row_number in range(row_count):
                writer.writerow([row_number])


if __name__ == "__main__":
    unittest.main()
