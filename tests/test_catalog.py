"""Tests for normalized product catalog loading and validation."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from catalog import (
    MANUFACTURER_FIELDS,
    MOUNT_FIELDS,
    PRODUCT_ALIAS_FIELDS,
    PRODUCT_FIELDS,
    CatalogValidationError,
    Manufacturer,
    Mount,
    Product,
    load_manufacturers,
    load_mounts,
    load_product_aliases,
    load_products,
)


class CatalogTests(unittest.TestCase):
    def test_loads_all_repository_catalog_files(self) -> None:
        data_directory = PROJECT_ROOT / "data"
        manufacturers = load_manufacturers(data_directory / "manufacturers.csv")
        mounts = load_mounts(data_directory / "mounts.csv")
        products = load_products(
            data_directory / "products.csv", manufacturers, mounts
        )
        aliases = load_product_aliases(
            data_directory / "product_aliases.csv", products
        )

        self.assertEqual(len(products), 34)
        self.assertEqual(len(aliases), 54)
        self.assertEqual(len(manufacturers), 13)
        self.assertEqual(len(mounts), 10)
        self.assertTrue(all(isinstance(item, Product) for item in products))

    def test_duplicate_product_ids_are_rejected(self) -> None:
        rows = [self.product_row(), self.product_row(id="TEST-PRODUCT")]
        error = self.load_products_error(rows)
        self.assert_error(error, "row 3", "field 'id'", "duplicate")

    def test_missing_required_product_field_is_rejected(self) -> None:
        error = self.load_products_error([self.product_row(product_type="")])
        self.assert_error(
            error, "row 2", "field 'product_type'", "required value is missing"
        )

    def test_invalid_numeric_values_are_rejected(self) -> None:
        for field, value in (
            ("release_year", "not-a-year"),
            ("price_new", "not-a-price"),
            ("liquidity_score", "not-a-score"),
        ):
            with self.subTest(field=field):
                error = self.load_products_error(
                    [self.product_row(**{field: value})]
                )
                self.assert_error(error, "row 2", f"field '{field}'", value)

    def test_empty_optional_prices_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "products.csv"
            self.write_csv(csv_path, PRODUCT_FIELDS, [self.product_row()])
            product = load_products(
                csv_path, self.manufacturers(), self.mounts()
            )[0]

        self.assertIsNone(product.price_new)
        self.assertIsNone(product.price_used)
        self.assertIsNone(product.price_good_deal)
        self.assertIsNone(product.price_max_buy)

    def test_unknown_manufacturer_is_rejected(self) -> None:
        error = self.load_products_error(
            [self.product_row(brand="Unknown Brand")]
        )
        self.assert_error(error, "row 2", "field 'brand'", "unknown manufacturer")

    def test_unknown_mount_is_rejected(self) -> None:
        error = self.load_products_error(
            [self.product_row(native_mount="unknown-mount")]
        )
        self.assert_error(error, "row 2", "field 'native_mount'", "unknown mount")

    def test_duplicate_aliases_are_rejected_case_insensitively(self) -> None:
        rows = [
            self.alias_row(alias="test alias"),
            self.alias_row(alias="TEST ALIAS"),
        ]
        error = self.load_aliases_error(rows)
        self.assert_error(error, "row 3", "field 'alias'", "normalized")

    def test_aliases_referencing_unknown_products_are_rejected(self) -> None:
        error = self.load_aliases_error(
            [self.alias_row(product_id="unknown-product")]
        )
        self.assert_error(error, "row 2", "field 'product_id'", "unknown product ID")

    def test_duplicate_manufacturer_ids_are_rejected(self) -> None:
        rows = [
            self.manufacturer_row(),
            self.manufacturer_row(id="TEST-BRAND", normalized_name="other brand"),
        ]
        error = self.load_reference_error(
            MANUFACTURER_FIELDS, rows, load_manufacturers, "manufacturers.csv"
        )
        self.assert_error(error, "row 3", "field 'id'", "duplicate")

    def test_duplicate_normalized_manufacturer_names_are_rejected(self) -> None:
        rows = [
            self.manufacturer_row(),
            self.manufacturer_row(id="other-brand", normalized_name="TEST BRAND"),
        ]
        error = self.load_reference_error(
            MANUFACTURER_FIELDS, rows, load_manufacturers, "manufacturers.csv"
        )
        self.assert_error(
            error, "row 3", "field 'normalized_name'", "duplicate"
        )

    def test_duplicate_mount_ids_are_rejected(self) -> None:
        rows = [self.mount_row(), self.mount_row(id="TEST-MOUNT", name="Other")]
        error = self.load_reference_error(
            MOUNT_FIELDS, rows, load_mounts, "mounts.csv"
        )
        self.assert_error(error, "row 3", "field 'id'", "duplicate")

    def test_duplicate_mount_names_are_rejected(self) -> None:
        rows = [self.mount_row(), self.mount_row(id="other-mount", name="TEST MOUNT")]
        error = self.load_reference_error(
            MOUNT_FIELDS, rows, load_mounts, "mounts.csv"
        )
        self.assert_error(error, "row 3", "field 'name'", "duplicate")

    def load_products_error(self, rows: List[Dict[str, str]]) -> Exception:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "products.csv"
            self.write_csv(csv_path, PRODUCT_FIELDS, rows)
            with self.assertRaises(CatalogValidationError) as context:
                load_products(csv_path, self.manufacturers(), self.mounts())
        return context.exception

    def load_aliases_error(self, rows: List[Dict[str, str]]) -> Exception:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "product_aliases.csv"
            self.write_csv(csv_path, PRODUCT_ALIAS_FIELDS, rows)
            products = [
                Product(
                    id="test-product",
                    category="Camera",
                    product_type="Mirrorless",
                    brand="Test Brand",
                    model="Test Model",
                    version="",
                    native_mount="test-mount",
                    release_year=None,
                    price_new=None,
                    price_used=None,
                    price_good_deal=None,
                    price_max_buy=None,
                    liquidity_score=None,
                    future_interest_score=None,
                    creative_value_score=None,
                    notes="",
                )
            ]
            with self.assertRaises(CatalogValidationError) as context:
                load_product_aliases(csv_path, products)
        return context.exception

    def load_reference_error(
        self, fields: Sequence[str], rows: List[Dict[str, str]], loader, filename: str
    ) -> Exception:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / filename
            self.write_csv(csv_path, fields, rows)
            with self.assertRaises(CatalogValidationError) as context:
                loader(csv_path)
        return context.exception

    @staticmethod
    def assert_error(error: Exception, *parts: str) -> None:
        message = str(error)
        for part in parts:
            if part not in message:
                raise AssertionError(f"{part!r} not found in {message!r}")

    @staticmethod
    def manufacturers() -> List[Manufacturer]:
        return [Manufacturer("test-brand", "Test Brand", "test brand", "")]

    @staticmethod
    def mounts() -> List[Mount]:
        return [Mount("test-mount", "Test Mount", "Lens mount", "")]

    @staticmethod
    def product_row(**overrides: str) -> Dict[str, str]:
        row = {field: "" for field in PRODUCT_FIELDS}
        row.update(
            {
                "id": "test-product",
                "category": "Camera",
                "product_type": "Mirrorless",
                "brand": "Test Brand",
                "model": "Test Model",
                "native_mount": "test-mount",
                "release_year": "2024",
            }
        )
        row.update(overrides)
        return row

    @staticmethod
    def alias_row(**overrides: str) -> Dict[str, str]:
        row = {
            "alias": "test alias",
            "product_id": "test-product",
            "alias_type": "common_name",
            "notes": "",
        }
        row.update(overrides)
        return row

    @staticmethod
    def manufacturer_row(**overrides: str) -> Dict[str, str]:
        row = {
            "id": "test-brand",
            "name": "Test Brand",
            "normalized_name": "test brand",
            "notes": "",
        }
        row.update(overrides)
        return row

    @staticmethod
    def mount_row(**overrides: str) -> Dict[str, str]:
        row = {
            "id": "test-mount",
            "name": "Test Mount",
            "mount_type": "Lens mount",
            "notes": "",
        }
        row.update(overrides)
        return row

    @staticmethod
    def write_csv(
        csv_path: Path, fields: Sequence[str], rows: List[Dict[str, str]]
    ) -> None:
        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
