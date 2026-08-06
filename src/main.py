"""Minimal command-line entry point for Photo Market Intelligence."""

from __future__ import annotations

import csv
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Optional

from catalog import (
    CatalogValidationError,
    load_manufacturers,
    load_mounts,
    load_product_aliases,
    load_products,
)
from connectors import ConnectorManager, MockConnector, SearchQuery
from decision import DecisionEngine, MarketStatistics, NewAlternative
from decision.explanations import format_report_summary


ROW_COUNT_FILES = {
    "Wishlist": "wishlist.csv",
    "Listings": "listings.csv",
}


def count_rows(csv_path: Path) -> int:
    if not csv_path.is_file():
        raise FileNotFoundError(f"required CSV file not found: {csv_path}")
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        return sum(1 for _ in csv.DictReader(csv_file))


def run(
    project_root: Optional[Path] = None,
    operational_directory: Optional[Path] = None,
) -> int:
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
        manager = ConnectorManager(
            [MockConnector(retry_count=1)],
            operational_directory or data_directory,
        )
        connector_run = manager.search(SearchQuery("Sony A7 IV"))
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
    for connector_result in connector_run.connector_results:
        print(f"Connector: {connector_result.connector_name}")
        print(f"Connector health: {connector_result.health.status.value}")
        print(f"Connector listings: {len(connector_result.listings)}")
        print(f"Connector incidents: {connector_result.incident_count}")
    products_by_id = {product.id: product for product in products}
    example_ids = {
        "sony-alpha-a7-iv", "sigma-24-70mm-f2-8-dg-dn-ii-art"
    }
    if example_ids.issubset(products_by_id):
        decision_engine = DecisionEngine(as_of=date(2026, 4, 1))
        clean_listing = MockConnector(scenario="clean_with_warranty").search(
            SearchQuery("Sony A7 IV")
        )[0]
        clean_listing = replace(clean_listing, price=1200.0, shutter_count=20_000)
        clean_report = decision_engine.evaluate(
            products_by_id["sony-alpha-a7-iv"],
            clean_listing,
            MarketStatistics(1400.0, 1150.0, 1595.0, 20, -2.0, 90, "EUR"),
            NewAlternative(1595.0, "EUR", 24, 30, 95.0, "Authorized retailer"),
        )
        cracked_listing = MockConnector(scenario="cracked_lens").search(
            SearchQuery("Sigma 24-70 DG DN II")
        )[0]
        cracked_report = decision_engine.evaluate(
            products_by_id["sigma-24-70mm-f2-8-dg-dn-ii-art"],
            cracked_listing,
            MarketStatistics(1050.0, 900.0, 1250.0, 12, -1.0, 90, "EUR"),
            NewAlternative(1250.0, "EUR", 24, 30, 95.0, "Authorized retailer"),
        )
        for line in format_report_summary("clean used versus new", clean_report):
            print(line)
        for line in format_report_summary("low price with cracked lens", cracked_report):
            print(line)
    print("System ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
