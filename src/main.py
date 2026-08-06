"""Minimal command-line entry point for Photo Market Intelligence."""

from __future__ import annotations

import csv
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from analyzers import DescriptionAnalyzer
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
from knowledge import ProductMatcher
from market import MarketEngine
from memory import (
    OwnedItem, PurchaseCondition, UserPreferences, WishlistItem,
    WishlistPriority, WishlistStatus, build_user_context,
)
from ownership import (
    OwnershipEngine, OwnershipHorizon, PurchaseOption, PurchaseType,
)
from ownership.explanations import format_comparison


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
    example_description = (
        "Sony A7 IV con circa 60k scatti, fattura presente, scatola originale "
        "e tre batterie originali Sony. Piccolo graffio sulla scocca. "
        "Perfettamente funzionante."
    )
    analysis = DescriptionAnalyzer(as_of=date(2026, 4, 15)).analyze(
        "Sony A7 IV", example_description, "Camera"
    )
    print(f"Extracted shutter count: {analysis.shutter_count}")
    print(f"Invoice available: {analysis.invoice_available}")
    print(f"Original box available: {analysis.original_box_available}")
    print(f"Extracted accessories: {'; '.join(analysis.accessories) or 'None'}")
    print(
        "Extracted defects: "
        + ("; ".join(
            f"{item.category}/{item.severity}: {item.description}"
            for item in analysis.defects
        ) or "None")
    )
    print(f"Seller claims: {'; '.join(analysis.seller_claims) or 'None'}")
    print(f"Description missing information: {'; '.join(analysis.missing_information) or 'None'}")
    print(f"Description analysis confidence: {analysis.confidence}")
    matcher = ProductMatcher(products, aliases)
    recognition_examples = (
        ("single product", "Sony A7IV ILCE-7M4 corpo macchina"),
        ("kit", "Sony A7 IV + Sigma 24-70 DG DN II + DJI RS 4"),
        ("first generation", "Sigma 24-70 DG DN prima serie"),
    )
    for label, title in recognition_examples:
        recognition = matcher.recognize(title, "")
        primary = products_by_id.get(recognition.product_id)
        print(f"Recognition example: {label}")
        print(
            "Recognized primary product: "
            + (
                f"{primary.brand} {primary.model} {primary.version}".strip()
                if primary else "None"
            )
        )
        print(f"Recognition confidence: {recognition.confidence}")
        print(
            "Recognition candidates: "
            + ("; ".join(candidate.product_id for candidate in recognition.candidates) or "None")
        )
        print(f"Recognition ambiguous: {recognition.ambiguous}")
        print(f"Recognition warnings: {'; '.join(recognition.warnings) or 'None'}")
    market_product = products_by_id.get("sony-alpha-a7-iv")
    if market_product is not None:
        market_created_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
        base_listing = MockConnector(scenario="clean_with_warranty").search(
            SearchQuery("Sony A7 IV")
        )[0]
        demo_prices = [1100.0, 1110.0, 1120.0, 1130.0, 1140.0,
                       1150.0, 1160.0, 1170.0, 1180.0, 5000.0]
        market_listings = [
            replace(
                base_listing,
                external_id=f"market-{index}",
                url=f"https://example.invalid/market-{index}",
                price=price,
                detected_at=market_created_at - timedelta(days=index),
            )
            for index, price in enumerate(demo_prices)
        ]
        listing_ids = [listing.external_id for listing in market_listings]
        market_snapshot = MarketEngine(
            "Italy", "EUR", "USED",
            recognized_product_ids={item: market_product.id for item in listing_ids},
            recognition_confidence={item: 100 for item in listing_ids},
            description_confidence={item: 100 for item in listing_ids},
            description_evidence_count={item: 5 for item in listing_ids},
            listing_segments={item: "USED" for item in listing_ids},
            source_countries={item: "Italy" for item in listing_ids},
            warranty_clarity={item: True for item in listing_ids},
            accessory_completeness={item: True for item in listing_ids},
            created_at=market_created_at,
        ).build_snapshot(market_product, market_listings)
        print("Market example: Sony A7 IV used market")
        print(f"Market median: {market_snapshot.median_price:.2f}")
        print(f"Market mean: {market_snapshot.mean_price:.2f}")
        print(f"Market outliers: {market_snapshot.outlier_count}")
        print(f"Market confidence: {market_snapshot.market_confidence}")
        print(f"Listing quality average: {market_snapshot.listing_quality_average:.2f}")
        print(
            "Estimated 12-month depreciation: "
            + (
                f"{market_snapshot.estimated_12_month_depreciation:.2f}%"
                if market_snapshot.estimated_12_month_depreciation is not None
                else "Unavailable"
            )
        )
        used_ownership_market = replace(
            market_snapshot,
            median_price=1400.0,
            estimated_12_month_depreciation=10.0,
            estimated_24_month_depreciation=20.0,
        )
        new_ownership_market = replace(
            used_ownership_market,
            segment="NEW",
            median_price=1595.0,
            estimated_12_month_depreciation=None,
            estimated_24_month_depreciation=None,
        )
        new_camera_option = PurchaseOption(
            option_id="a7-iv-new", purchase_type=PurchaseType.NEW,
            purchase_price=1595.0, currency="EUR", warranty_months=24,
            return_window_days=14, estimated_landed_cost=1595.0,
            shutter_count=0, defects=[], accessories=[],
            seller_reliability_score=95, market_snapshot=new_ownership_market,
            notes="Authorized retailer", source_country="Italy",
            target_market_country="Italy", transferable_warranty=True,
            invoice_available=True, condition_known=True,
        )
        used_camera_option = PurchaseOption(
            option_id="a7-iv-used", purchase_type=PurchaseType.USED,
            purchase_price=1200.0, currency="EUR", warranty_months=0,
            return_window_days=0, estimated_landed_cost=1200.0,
            shutter_count=60_000, defects=[], accessories=[],
            seller_reliability_score=95, market_snapshot=used_ownership_market,
            notes="Private used listing", source_country="Italy",
            target_market_country="Italy", transferable_warranty=False,
            invoice_available=True, condition_known=True,
        )
        ownership_engine = OwnershipEngine()
        camera_comparison = ownership_engine.compare(
            market_product, [new_camera_option, used_camera_option],
            OwnershipHorizon(12, "MEDIUM", True),
        )
        for line in format_comparison("Sony A7 IV new versus used", camera_comparison):
            print(line)

        lens_product = products_by_id.get(
            "sigma-24-70mm-f2-8-dg-dn-ii-art"
        )
        if lens_product is not None:
            used_lens_market = replace(
                used_ownership_market,
                product_id=lens_product.id, median_price=900.0,
            )
            new_lens_market = replace(
                used_lens_market, segment="NEW", median_price=1250.0,
                estimated_12_month_depreciation=None,
                estimated_24_month_depreciation=None,
            )
            new_lens_option = PurchaseOption(
                "lens-new", PurchaseType.NEW, 1250.0, "EUR", 24, 14,
                1250.0, None, [], [], 95, new_lens_market,
                "Authorized retailer", "Italy", "Italy", True, True, True,
            )
            used_lens_option = PurchaseOption(
                "lens-cracked-used", PurchaseType.USED, 300.0, "EUR", 0, 0,
                300.0, None, cracked_listing.defects, [], 80,
                used_lens_market, "Cracked front element", "Italy", "Italy",
                False, True, True,
            )
            cracked_comparison = ownership_engine.compare(
                lens_product, [new_lens_option, used_lens_option],
                OwnershipHorizon(12, "MEDIUM", True),
            )
            for line in format_comparison(
                "cracked lens new versus used", cracked_comparison
            ):
                print(line)
    memory_ids = {
        "sony-alpha-a7-iv", "sony-fe-50mm-f1-8",
        "sigma-24-70mm-f2-8-dg-dn-ii-art", "sony-fe-50mm-f1-4-gm",
        "sony-fe-70-200mm-f2-8-gm-oss-ii",
    }
    if memory_ids.issubset(products_by_id):
        memory_time = datetime(2026, 8, 1, tzinfo=timezone.utc)
        inventory = [
            OwnedItem("body-a", "sony-alpha-a7-iv", date(2024, 1, 1), 1500, "EUR", PurchaseCondition.NEW, 0, 20_000, None, [], "BODY-A", "", True),
            OwnedItem("prime-a", "sony-fe-50mm-f1-8", date(2024, 1, 1), 150, "EUR", PurchaseCondition.NEW, None, None, None, [], None, "", True),
        ]
        wishlist = [
            WishlistItem("wish-standard", "sigma-24-70mm-f2-8-dg-dn-ii-art", 900, "EUR", WishlistPriority.HIGH, PurchaseCondition.EITHER, None, "Standard zoom", WishlistStatus.ACTIVE, memory_time, memory_time),
            WishlistItem("wish-prime", "sony-fe-50mm-f1-4-gm", None, "EUR", WishlistPriority.MEDIUM, PurchaseCondition.USED, None, "Faster prime", WishlistStatus.ACTIVE, memory_time, memory_time),
            WishlistItem("wish-tele", "sony-fe-70-200mm-f2-8-gm-oss-ii", 1800, "EUR", WishlistPriority.MEDIUM, PurchaseCondition.EITHER, None, "Telephoto zoom", WishlistStatus.ACTIVE, memory_time, memory_time),
        ]
        user_context = build_user_context(
            inventory, wishlist, [], UserPreferences(target_market_country="Italy"),
            products, date(2026, 8, 1),
        )
        print("User memory example")
        print(f"Owned products: {'; '.join(user_context.owned_product_ids)}")
        print("Active user wishlist: " + "; ".join(item.product_id for item in user_context.active_wishlist))
        for item in user_context.wishlist_context:
            print(f"Wishlist flags {item.product_id}: {'; '.join(flag.value for flag in item.flags)}")
        print(f"Inventory gaps: {'; '.join(user_context.missing_system_gaps) or 'None'}")
        print(f"Recent decision count: {len(user_context.recent_decisions)}")
    print("Dashboard:")
    print("python3 -m src.dashboard.server")
    print("Radar once:")
    print("python3 -m src.radar.scheduler --once")
    print("MVP modules: ready")
    print("System ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
