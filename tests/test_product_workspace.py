"""Product-centric workspace and canonical listing-index tests."""

from __future__ import annotations

import ast
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catalog import load_product_aliases, load_products
from dashboard.product_workspace import ProductWorkspaceBuilder
from dashboard.view_models import ProductView
from radar.models import RadarListing


NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)


def listing(
    listing_id: str, segment: str, price: float, currency: str = "EUR",
    product_id: str = "sony-alpha-a7-iv", active: bool = True,
    confidence: int = 100, missing=None, warnings=None,
) -> RadarListing:
    title = f"Sony A7 IV {segment}"
    description = "60000 scatti" if segment == "USED" else "Nuova"
    return RadarListing(
        "run", listing_id, listing_id, "manual", "Subito.it",
        f"https://example.test/{listing_id}", title, description, price,
        currency, "IT", segment, segment, NOW, NOW, NOW, product_id,
        confidence, 85, f"url:{listing_id}", active, f"sha256:{listing_id}",
        60000 if segment == "USED" else None, None, None, None, [], [], [],
        list(missing or ["warranty status"]), list(warnings or []),
    )


class ProductWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.products = load_products(ROOT / "data" / "products.csv")
        cls.aliases = load_product_aliases(ROOT / "data" / "product_aliases.csv", cls.products)
        cls.product = next(item for item in cls.products if item.id == "sony-alpha-a7-iv")

    def view(self) -> ProductView:
        product = self.product
        return ProductView(
            product.id, "Sony Alpha A7 IV", product.brand, product.model,
            product.version, product.category, product.product_type,
            product.native_mount, product.release_year,
        )

    def test_canonical_index_excludes_review_and_inactive_listings(self) -> None:
        valid = listing("valid", "USED", 1200)
        inactive = listing("inactive", "NEW", 1595, active=False)
        unresolved = listing("unknown", "USED", 900, product_id="", confidence=40)
        builder = ProductWorkspaceBuilder(self.products, [valid, inactive, unresolved])
        self.assertEqual(
            [item.listing_id for item in builder.active_listings_for_product(self.product.id)],
            ["valid"],
        )
        inbox = {item["listing_id"]: item for item in builder.listing_views()}
        self.assertFalse(inbox["inactive"]["active"])
        self.assertTrue(inbox["unknown"]["needs_review"])
        self.assertIsNone(inbox["unknown"]["product_url"])
        self.assertEqual(inbox["valid"]["state"]["lifecycle"], "EVALUATED")
        self.assertTrue(inbox["valid"]["state"]["has_missing_information"])
        self.assertFalse(inbox["valid"]["state"]["needs_product_review"])

    def test_workspace_card_counts_lowest_prices_and_honest_sample(self) -> None:
        values = [listing("new", "NEW", 1595), listing("used", "USED", 1200)]
        builder = ProductWorkspaceBuilder(self.products, values)
        workspace = builder.build(self.product, self.view(), {}, [],)
        enriched = builder.enrich_product(self.view(), workspace)
        self.assertEqual(workspace.offer_count, 2)
        self.assertEqual(workspace.lowest_new_offer["price"], 1595)
        self.assertEqual(workspace.lowest_used_offer["price"], 1200)
        self.assertEqual(enriched.active_offer_count, 2)
        self.assertEqual(enriched.lowest_new_offer, 1595)
        self.assertEqual(enriched.lowest_used_offer, 1200)
        self.assertIn("Singola offerta", enriched.market_sample_label)
        key = "new:used"
        self.assertIn(key, workspace.available_comparisons)
        comparison = workspace.available_comparisons[key]
        self.assertEqual(comparison["nominal_saving"], 395)
        self.assertAlmostEqual(comparison["saving_percentage"], 24.8, places=1)
        self.assertEqual(comparison["recommendation"], "INSUFFICIENT_DATA")
        self.assertEqual(workspace.overall_conclusion["result"], "INSUFFICIENT_DATA")

    def test_zero_three_same_segment_and_cross_currency_offers(self) -> None:
        empty_builder = ProductWorkspaceBuilder(self.products, [])
        empty = empty_builder.build(self.product, self.view(), {}, [])
        self.assertEqual(empty.offer_count, 0)
        self.assertIsNone(empty.lowest_new_offer)
        same = [listing("one", "USED", 1200), listing("two", "USED", 1250), listing("three", "USED", 1300)]
        same_workspace = ProductWorkspaceBuilder(self.products, same).build(self.product, self.view(), {}, [])
        self.assertEqual(same_workspace.offer_count, 3)
        self.assertEqual(same_workspace.available_comparisons, {})
        mixed = [listing("eur", "USED", 1200), listing("usd", "NEW", 1595, "USD")]
        mixed_workspace = ProductWorkspaceBuilder(self.products, mixed).build(self.product, self.view(), {}, [])
        self.assertEqual(mixed_workspace.offer_count, 2)
        self.assertEqual(mixed_workspace.available_comparisons, {})

    def test_structural_contradiction_is_review_not_missing_data(self) -> None:
        contradictory = listing("bad", "USED", 1000, warnings=["contradictory functional claims"])
        builder = ProductWorkspaceBuilder(self.products, [contradictory])
        state = builder.listing_state(contradictory)
        self.assertTrue(state.needs_product_review)
        self.assertTrue(state.has_contradictions)
        ordinary = replace(contradictory, listing_id="ordinary", duplicate_key="ordinary", warnings=[])
        state = ProductWorkspaceBuilder(self.products, [ordinary]).listing_state(ordinary)
        self.assertFalse(state.needs_product_review)
        self.assertTrue(state.has_missing_information)

    def test_legacy_unresolved_listing_is_derived_without_mutating_source(self) -> None:
        unresolved = listing("legacy", "USED", 1200, product_id="")
        builder = ProductWorkspaceBuilder(self.products, [unresolved], self.aliases)
        attached = builder.active_listings_for_product("sony-alpha-a7-iv")
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0].product_id, "sony-alpha-a7-iv")
        self.assertEqual(unresolved.product_id, "")

    def test_python_39_compatibility(self) -> None:
        for path in (ROOT / "src" / "dashboard" / "product_workspace.py", ROOT / "src" / "dashboard" / "view_models.py"):
            ast.parse(path.read_text(), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
