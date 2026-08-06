"""Minimal command-line entry point for Photo Market Intelligence."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Optional

from catalog import (
    CatalogValidationError,
    load_manufacturers,
    load_mounts,
    load_product_aliases,
    load_products,
)


ROW_COUNT_FILES = {
    "Wishlist": "wishlist.csv",
    "Listings": "listings.csv",
}


def count_rows(csv_path: Path) -> int:
    if not csv_path.is_file():
        raise FileNotFoundError(f"required CSV file not found: {csv_path}")
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        return sum(1 for _ in csv.DictReader(csv_file))


def run(project_root: Optional[Path] = None) -> int:
    root = project_root or Path(__file__).resolve().parents[1]
    data_directory = root / "data"

    try:
        manufacturers = load_manufacturers(data_directory / "manufacturers.csv")
        mounts = load_mounts(data_directory / "mounts.csv")
        products = load_products(
            data_directory / "products.csv", manufacturers, mounts
        )
        aliases = load_product_aliases(
            data_directory / "product_aliases.csv", products
        )
        row_counts = {
            label: count_rows(data_directory / filename)
            for label, filename in ROW_COUNT_FILES.items()
        }
    except (CatalogValidationError, OSError, csv.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print("Photo Market Intelligence")
    print("Status: OK")
    print(f"Products: {len(products)}")
    print(f"Product aliases: {len(aliases)}")
    print(f"Manufacturers: {len(manufacturers)}")
    print(f"Mounts: {len(mounts)}")
    for label, count in row_counts.items():
        print(f"{label}: {count}")
    print("System ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
