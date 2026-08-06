"""Loading and validation for normalized product catalog data."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PRODUCT_FIELDS = (
    "id",
    "category",
    "product_type",
    "brand",
    "model",
    "version",
    "native_mount",
    "release_year",
    "price_new",
    "price_used",
    "price_good_deal",
    "price_max_buy",
    "liquidity_score",
    "future_interest_score",
    "creative_value_score",
    "notes",
)
PRODUCT_ALIAS_FIELDS = ("alias", "product_id", "alias_type", "notes")
MANUFACTURER_FIELDS = ("id", "name", "normalized_name", "notes")
MOUNT_FIELDS = ("id", "name", "mount_type", "notes")

REQUIRED_PRODUCT_FIELDS = (
    "id",
    "category",
    "product_type",
    "brand",
    "model",
    "native_mount",
)


class CatalogValidationError(ValueError):
    """Raised when a catalog CSV contains invalid data."""


@dataclass(frozen=True)
class Product:
    id: str
    category: str
    product_type: str
    brand: str
    model: str
    version: str
    native_mount: str
    release_year: Optional[int]
    price_new: Optional[float]
    price_used: Optional[float]
    price_good_deal: Optional[float]
    price_max_buy: Optional[float]
    liquidity_score: Optional[float]
    future_interest_score: Optional[float]
    creative_value_score: Optional[float]
    notes: str


@dataclass(frozen=True)
class ProductAlias:
    alias: str
    product_id: str
    alias_type: str
    notes: str


@dataclass(frozen=True)
class Manufacturer:
    id: str
    name: str
    normalized_name: str
    notes: str


@dataclass(frozen=True)
class Mount:
    id: str
    name: str
    mount_type: str
    notes: str


def _error(csv_path: Path, row_number: int, field: str, message: str) -> None:
    raise CatalogValidationError(
        f"{csv_path}: row {row_number}, field '{field}': {message}"
    )


def _read_rows(
    csv_path: Path, expected_fields: Sequence[str]
) -> Tuple[csv.DictReader, object]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"required CSV file not found: {csv_path}")

    csv_file = csv_path.open(newline="", encoding="utf-8")
    reader = csv.DictReader(csv_file)
    for field in expected_fields:
        if reader.fieldnames is None or field not in reader.fieldnames:
            csv_file.close()
            _error(csv_path, 1, field, "required column is missing")
    return reader, csv_file


def _normalized_row(row: Dict[str, str], fields: Sequence[str]) -> Dict[str, str]:
    return {field: (row.get(field) or "").strip() for field in fields}


def _require_fields(
    row: Dict[str, str], fields: Iterable[str], csv_path: Path, row_number: int
) -> None:
    for field in fields:
        if not row[field]:
            _error(csv_path, row_number, field, "required value is missing")


def _parse_integer(
    value: str, csv_path: Path, row_number: int, field: str
) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        _error(csv_path, row_number, field, f"expected an integer, got {value!r}")


def _parse_number(
    value: str, csv_path: Path, row_number: int, field: str
) -> Optional[float]:
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        _error(csv_path, row_number, field, f"expected a number, got {value!r}")
    if not math.isfinite(number):
        _error(csv_path, row_number, field, f"expected a finite number, got {value!r}")
    return number


def _check_duplicate(
    seen: Dict[str, int],
    value: str,
    csv_path: Path,
    row_number: int,
    field: str,
    case_insensitive: bool = True,
) -> None:
    key = value.casefold() if case_insensitive else value
    if key in seen:
        _error(
            csv_path,
            row_number,
            field,
            f"duplicate value {value!r}; first seen on row {seen[key]}",
        )
    seen[key] = row_number


def normalize_alias(value: str) -> str:
    """Normalize an alias for storage and case-insensitive matching."""
    return " ".join(value.strip().casefold().split())


def load_manufacturers(csv_path: Path) -> List[Manufacturer]:
    """Load manufacturers and reject duplicate IDs or normalized names."""
    reader, csv_file = _read_rows(csv_path, MANUFACTURER_FIELDS)
    manufacturers = []
    seen_ids: Dict[str, int] = {}
    seen_names: Dict[str, int] = {}
    try:
        for row_number, source_row in enumerate(reader, start=2):
            row = _normalized_row(source_row, MANUFACTURER_FIELDS)
            _require_fields(
                row, ("id", "name", "normalized_name"), csv_path, row_number
            )
            _check_duplicate(seen_ids, row["id"], csv_path, row_number, "id")
            _check_duplicate(
                seen_names,
                row["normalized_name"],
                csv_path,
                row_number,
                "normalized_name",
            )
            manufacturers.append(Manufacturer(**row))
    finally:
        csv_file.close()
    return manufacturers


def load_mounts(csv_path: Path) -> List[Mount]:
    """Load mounts and reject duplicate IDs or names."""
    reader, csv_file = _read_rows(csv_path, MOUNT_FIELDS)
    mounts = []
    seen_ids: Dict[str, int] = {}
    seen_names: Dict[str, int] = {}
    try:
        for row_number, source_row in enumerate(reader, start=2):
            row = _normalized_row(source_row, MOUNT_FIELDS)
            _require_fields(row, ("id", "name", "mount_type"), csv_path, row_number)
            _check_duplicate(seen_ids, row["id"], csv_path, row_number, "id")
            _check_duplicate(seen_names, row["name"], csv_path, row_number, "name")
            mounts.append(Mount(**row))
    finally:
        csv_file.close()
    return mounts


def load_products(
    csv_path: Path,
    manufacturers: Optional[Sequence[Manufacturer]] = None,
    mounts: Optional[Sequence[Mount]] = None,
) -> List[Product]:
    """Load products and validate their normalized catalog references."""
    data_directory = csv_path.parent
    if manufacturers is None:
        manufacturers = load_manufacturers(data_directory / "manufacturers.csv")
    if mounts is None:
        mounts = load_mounts(data_directory / "mounts.csv")

    manufacturer_names = {item.name.casefold() for item in manufacturers}
    mount_ids = {item.id.casefold() for item in mounts}
    reader, csv_file = _read_rows(csv_path, PRODUCT_FIELDS)
    products = []
    seen_ids: Dict[str, int] = {}
    try:
        for row_number, source_row in enumerate(reader, start=2):
            row = _normalized_row(source_row, PRODUCT_FIELDS)
            _require_fields(row, REQUIRED_PRODUCT_FIELDS, csv_path, row_number)
            _check_duplicate(seen_ids, row["id"], csv_path, row_number, "id")

            if row["brand"].casefold() not in manufacturer_names:
                _error(
                    csv_path,
                    row_number,
                    "brand",
                    f"unknown manufacturer {row['brand']!r}",
                )
            if row["native_mount"].casefold() not in mount_ids:
                _error(
                    csv_path,
                    row_number,
                    "native_mount",
                    f"unknown mount {row['native_mount']!r}",
                )

            products.append(
                Product(
                    id=row["id"],
                    category=row["category"],
                    product_type=row["product_type"],
                    brand=row["brand"],
                    model=row["model"],
                    version=row["version"],
                    native_mount=row["native_mount"],
                    release_year=_parse_integer(
                        row["release_year"], csv_path, row_number, "release_year"
                    ),
                    price_new=_parse_number(
                        row["price_new"], csv_path, row_number, "price_new"
                    ),
                    price_used=_parse_number(
                        row["price_used"], csv_path, row_number, "price_used"
                    ),
                    price_good_deal=_parse_number(
                        row["price_good_deal"],
                        csv_path,
                        row_number,
                        "price_good_deal",
                    ),
                    price_max_buy=_parse_number(
                        row["price_max_buy"], csv_path, row_number, "price_max_buy"
                    ),
                    liquidity_score=_parse_number(
                        row["liquidity_score"],
                        csv_path,
                        row_number,
                        "liquidity_score",
                    ),
                    future_interest_score=_parse_number(
                        row["future_interest_score"],
                        csv_path,
                        row_number,
                        "future_interest_score",
                    ),
                    creative_value_score=_parse_number(
                        row["creative_value_score"],
                        csv_path,
                        row_number,
                        "creative_value_score",
                    ),
                    notes=row["notes"],
                )
            )
    finally:
        csv_file.close()
    return products


def load_product_aliases(
    csv_path: Path, products: Optional[Sequence[Product]] = None
) -> List[ProductAlias]:
    """Load normalized aliases and validate their product references."""
    if products is None:
        products = load_products(csv_path.parent / "products.csv")
    product_ids = {product.id.casefold() for product in products}
    reader, csv_file = _read_rows(csv_path, PRODUCT_ALIAS_FIELDS)
    aliases = []
    seen_aliases: Dict[str, int] = {}
    try:
        for row_number, source_row in enumerate(reader, start=2):
            row = _normalized_row(source_row, PRODUCT_ALIAS_FIELDS)
            _require_fields(
                row, ("alias", "product_id", "alias_type"), csv_path, row_number
            )
            normalized_alias = normalize_alias(row["alias"])
            if row["alias"] != normalized_alias:
                _error(
                    csv_path,
                    row_number,
                    "alias",
                    f"alias must be normalized as {normalized_alias!r}",
                )
            _check_duplicate(
                seen_aliases, normalized_alias, csv_path, row_number, "alias"
            )
            if row["product_id"].casefold() not in product_ids:
                _error(
                    csv_path,
                    row_number,
                    "product_id",
                    f"unknown product ID {row['product_id']!r}",
                )
            aliases.append(ProductAlias(**row))
    finally:
        csv_file.close()
    return aliases
