"""Tests for privacy-safe user memory and smart wishlist V1."""

from __future__ import annotations

import ast
import csv
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catalog import load_products
from memory import (
    DecisionHistoryEntry, MemoryValidationError, OwnedItem, PurchaseCondition,
    UserPreferences, WishlistFlag, WishlistItem, WishlistPriority,
    WishlistStatus, build_user_context, initialize_user_data,
    load_decision_history, load_inventory, load_preferences, load_wishlist,
    normalize_listing_url, record_purchase, save_decision_history,
    save_inventory, save_preferences, save_wishlist, summarize_inventory,
)


class MemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.products = load_products(ROOT / "data" / "products.csv")
        self.now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        self.a7 = self.owned("body-a", "sony-alpha-a7-iv")

    def test_runtime_data_is_ignored_and_templates_are_tracked(self) -> None:
        ignore = (ROOT / ".gitignore").read_text()
        self.assertIn("data/user/", ignore)
        templates = ROOT / "data" / "templates"
        self.assertEqual(len(list(templates.glob("user_*.example.*"))), 4)

    def test_initialization_from_templates_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            user = Path(directory) / "user"
            initialize_user_data(ROOT / "data" / "templates", user)
            inventory = user / "user_inventory.csv"
            self.assertTrue(inventory.is_file())
            inventory.write_text("keep", encoding="utf-8")
            initialize_user_data(ROOT / "data" / "templates", user)
            self.assertEqual(inventory.read_text(), "keep")

    def test_valid_inventory_multiple_copies_and_inactive(self) -> None:
        with self.paths() as paths:
            items = [self.a7, self.owned("body-b", self.a7.product_id), replace(self.a7, item_id="old", active=False)]
            save_inventory(paths.inventory, items)
            loaded = load_inventory(paths.inventory, self.products)
            self.assertEqual(len(loaded), 3)
            self.assertFalse(loaded[-1].active)

    def test_unknown_product_and_unknown_csv_column(self) -> None:
        with self.paths() as paths:
            save_inventory(paths.inventory, [replace(self.a7, product_id="unknown")])
            with self.assertRaisesRegex(MemoryValidationError, "unknown product ID"):
                load_inventory(paths.inventory, self.products)
            paths.inventory.write_text("item_id,unknown\na,b\n", encoding="utf-8")
            with self.assertRaisesRegex(MemoryValidationError, "unknown column"):
                load_inventory(paths.inventory, self.products)

    def test_serial_reference_policy_and_public_context(self) -> None:
        with self.paths() as paths:
            save_inventory(paths.inventory, [replace(self.a7, serial_reference="***1234")])
            self.assertEqual(load_inventory(paths.inventory, self.products)[0].serial_reference, "***1234")
            save_inventory(paths.inventory, [replace(self.a7, serial_reference="ILCE7M4ABC123456")])
            with self.assertRaisesRegex(MemoryValidationError, "masked suffix"):
                load_inventory(paths.inventory, self.products)
        context = build_user_context([replace(self.a7, serial_reference="BODY-A")], [], [], UserPreferences(), self.products, date(2026, 8, 1))
        self.assertFalse(hasattr(context, "serial_reference"))

    def test_wishlist_duplicate_and_different_condition(self) -> None:
        with self.paths() as paths:
            first = self.wish("one", PurchaseCondition.NEW)
            save_wishlist(paths.wishlist, [first, replace(first, wishlist_id="two")])
            with self.assertRaisesRegex(MemoryValidationError, "duplicate active"):
                load_wishlist(paths.wishlist, self.products)
            save_wishlist(paths.wishlist, [first, replace(first, wishlist_id="two", purchase_condition_preference=PurchaseCondition.USED)])
            self.assertEqual(len(load_wishlist(paths.wishlist, self.products)), 2)

    def test_preferences_defaults_validation_and_unknown_key(self) -> None:
        defaults = UserPreferences()
        self.assertEqual((defaults.warranty_importance, defaults.resale_importance, defaults.weight_sensitivity, defaults.notification_threshold), (50, 50, 50, 80))
        with self.paths() as paths:
            save_preferences(paths.preferences, defaults)
            self.assertEqual(load_preferences(paths.preferences), defaults)
            value = json.loads(paths.preferences.read_text())
            value["secret"] = "retained"
            paths.preferences.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(MemoryValidationError, "unknown key"):
                load_preferences(paths.preferences)

    def test_url_normalization_and_credentials(self) -> None:
        path = Path("history.csv")
        normalized = normalize_listing_url("https://example.test/item?id=4&utm_source=x&ref=y#seller", path, 2)
        self.assertEqual(normalized, "https://example.test/item?id=4")
        with self.assertRaisesRegex(MemoryValidationError, "credentials"):
            normalize_listing_url("https://user:pass@example.test/item", path, 2)

    def test_decision_history_privacy_and_normalized_persistence(self) -> None:
        with self.paths() as paths:
            entry = self.decision("one", self.now, ["Fair price"])
            save_decision_history(paths.history, [replace(entry, listing_url=entry.listing_url + "?utm_campaign=x&id=7#x")])
            loaded = load_decision_history(paths.history, self.products)
            self.assertEqual(loaded[0].listing_url, "https://example.test/listing?id=7")
            for leaked in ("Email me at seller@example.com", "Call +39 333 123 4567"):
                with self.assertRaises(MemoryValidationError):
                    save_decision_history(paths.history, [replace(entry, reasons=[leaked])])

    def test_recent_decisions_are_sorted_limited_without_mutation(self) -> None:
        decisions = [self.decision("old", self.now - timedelta(days=1), []), self.decision("new", self.now, [])]
        original = list(decisions)
        context = build_user_context([], [], decisions, UserPreferences(), self.products, date(2026, 8, 1), 1)
        self.assertEqual([item.entry_id for item in context.recent_decisions], ["new"])
        self.assertEqual(decisions, original)

    def test_inventory_coverage_and_notes_are_not_parsed(self) -> None:
        coverage = summarize_inventory([
            self.a7, self.owned("prime", "sony-fe-50mm-f1-8"),
            self.owned("zoom", "sigma-24-70mm-f2-8-dg-dn-ii-art"),
        ], self.products)
        self.assertIn("sony-alpha-a7-iv", coverage.camera_bodies)
        self.assertIn("sony-fe-50mm-f1-8", coverage.primes)
        self.assertIn("STANDARD", coverage.focal_categories)
        product = replace(next(item for item in self.products if item.id == "sony-fe-50mm-f1-8"), model="Unknown lens", notes="70-200mm")
        coverage = summarize_inventory([self.owned("x", product.id)], [product])
        self.assertIn(product.id, coverage.unknown_focal_products)
        self.assertFalse(coverage.focal_categories["TELEPHOTO"])

    def test_multiple_flags_and_none_exclusivity(self) -> None:
        wish = replace(self.wish("flags", PurchaseCondition.USED), product_id=self.a7.product_id, currency="USD", target_date=date(2026, 1, 1), target_price=None)
        preferences = UserPreferences(default_purchase_condition=PurchaseCondition.NEW)
        context = build_user_context([self.a7], [wish], [], preferences, self.products, date(2026, 8, 1))
        flags = context.wishlist_context[0].flags
        self.assertEqual(flags[:4], [WishlistFlag.ALREADY_OWNED, WishlistFlag.CONDITION_CONFLICT, WishlistFlag.CURRENCY_CONFLICT, WishlistFlag.TARGET_DATE_PASSED])
        self.assertIn(WishlistFlag.TARGET_PRICE_MISSING, flags)
        self.assertNotIn(WishlistFlag.NONE, flags)
        clean = replace(self.wish("clean", PurchaseCondition.EITHER), target_price=900, product_id="sigma-24-70mm-f2-8-dg-dn-ii-art")
        no_flags = build_user_context([self.owned("zoom", clean.product_id)], [clean], [], UserPreferences(target_market_country="Italy"), self.products, date(2026, 8, 1)).wishlist_context[0]
        self.assertNotIn(WishlistFlag.NONE, no_flags.flags)  # exact ownership remains factual

    def test_none_when_no_flag_applies(self) -> None:
        clean = replace(self.wish("clean", PurchaseCondition.EITHER), target_price=900, product_id="dji-rs-4")
        context = build_user_context([], [clean], [], UserPreferences(target_market_country="Italy"), self.products, date(2026, 8, 1))
        self.assertEqual(context.wishlist_context[0].flags, [WishlistFlag.NONE])

    def test_complement_and_redundancy_flags(self) -> None:
        standard = replace(self.wish("standard", PurchaseCondition.EITHER), product_id="sigma-24-70mm-f2-8-dg-dn-ii-art", target_price=900)
        tele = replace(standard, wishlist_id="tele", product_id="sony-fe-70-200mm-f2-8-gm-oss-ii")
        inventory = [self.owned("prime", "sony-fe-50mm-f1-8")]
        contexts = build_user_context(inventory, [standard, tele], [], UserPreferences(target_market_country="Italy"), self.products, date(2026, 8, 1)).wishlist_context
        self.assertIn(WishlistFlag.COMPLEMENTS_INVENTORY, contexts[0].flags)
        self.assertIn(WishlistFlag.COMPLEMENTS_INVENTORY, contexts[1].flags)
        other_prime = replace(standard, product_id="sony-fe-50mm-f1-4-gm")
        flags = build_user_context(inventory, [other_prime], [], UserPreferences(), self.products, date(2026, 8, 1)).wishlist_context[0].flags
        self.assertIn(WishlistFlag.POSSIBLE_REDUNDANCY, flags)

    def test_purchase_transaction_and_condition_matching(self) -> None:
        with self.paths() as paths:
            wishlist = [self.wish("new", PurchaseCondition.NEW), self.wish("used", PurchaseCondition.USED), self.wish("either", PurchaseCondition.EITHER), replace(self.wish("paused", PurchaseCondition.USED), status=WishlistStatus.PAUSED)]
            save_inventory(paths.inventory, [])
            save_wishlist(paths.wishlist, wishlist)
            record_purchase(paths.inventory, paths.wishlist, [], wishlist, replace(self.a7, condition_at_purchase=PurchaseCondition.NEW), self.now, self.products)
            loaded = {item.wishlist_id: item for item in load_wishlist(paths.wishlist, self.products)}
            self.assertEqual(loaded["new"].status, WishlistStatus.PURCHASED)
            self.assertEqual(loaded["either"].status, WishlistStatus.PURCHASED)
            self.assertEqual(loaded["used"].status, WishlistStatus.ACTIVE)
            self.assertEqual(loaded["paused"].status, WishlistStatus.PAUSED)
            self.assertEqual(len(load_inventory(paths.inventory, self.products)), 1)

    def test_unknown_purchase_condition_closes_only_either(self) -> None:
        with self.paths() as paths:
            wishlist = [self.wish("new", PurchaseCondition.NEW), self.wish("either", PurchaseCondition.EITHER)]
            save_inventory(paths.inventory, []); save_wishlist(paths.wishlist, wishlist)
            record_purchase(paths.inventory, paths.wishlist, [], wishlist, replace(self.a7, condition_at_purchase=None), self.now, self.products)
            loaded = {item.wishlist_id: item.status for item in load_wishlist(paths.wishlist, self.products)}
            self.assertEqual(loaded, {"new": WishlistStatus.ACTIVE, "either": WishlistStatus.PURCHASED})

    def test_failed_second_replace_rolls_back_both(self) -> None:
        with self.paths() as paths:
            wishlist = [self.wish("either", PurchaseCondition.EITHER)]
            save_inventory(paths.inventory, []); save_wishlist(paths.wishlist, wishlist)
            before_inventory = paths.inventory.read_bytes(); before_wishlist = paths.wishlist.read_bytes()
            real_replace = os.replace
            calls = {"count": 0}
            def failing_replace(source, destination):
                calls["count"] += 1
                if calls["count"] == 2: raise OSError("simulated second replace failure")
                return real_replace(source, destination)
            with patch("memory.wishlist.os.replace", side_effect=failing_replace):
                with self.assertRaisesRegex(OSError, "second replace"):
                    record_purchase(paths.inventory, paths.wishlist, [], wishlist, self.a7, self.now, self.products)
            self.assertEqual(paths.inventory.read_bytes(), before_inventory)
            self.assertEqual(paths.wishlist.read_bytes(), before_wishlist)

    def test_malformed_csv_and_json(self) -> None:
        with self.paths() as paths:
            paths.inventory.write_text("item_id,extra\na,b,c\n", encoding="utf-8")
            with self.assertRaises(MemoryValidationError): load_inventory(paths.inventory, self.products)
            paths.preferences.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(MemoryValidationError, "malformed JSON"): load_preferences(paths.preferences)

    def test_sources_parse_as_python_3_9(self) -> None:
        for path in (ROOT / "src" / "memory").glob("*.py"):
            ast.parse(path.read_text(), feature_version=(3, 9))

    def owned(self, item_id, product_id):
        return OwnedItem(item_id, product_id, date(2024, 1, 1), 1000, "EUR", PurchaseCondition.USED, None, None, None, [], "BODY-A", "", True)

    def wish(self, wishlist_id, condition):
        return WishlistItem(wishlist_id, self.a7.product_id, 1000, "EUR", WishlistPriority.HIGH, condition, None, "", WishlistStatus.ACTIVE, self.now, self.now)

    def decision(self, entry_id, created, reasons):
        return DecisionHistoryEntry(entry_id, self.a7.product_id, "https://example.test/listing", "test", "MONITOR", 70, "EQUIVALENT", 1000, "EUR", reasons, "", created)

    def paths(self):
        return TemporaryPaths()


class TemporaryPaths:
    def __enter__(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.inventory = root / "inventory.csv"
        self.wishlist = root / "wishlist.csv"
        self.history = root / "history.csv"
        self.preferences = root / "preferences.json"
        return self

    def __exit__(self, *args):
        self.temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
