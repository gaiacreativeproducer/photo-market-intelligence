"""Tests for the localhost-only dashboard and full-catalog search."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catalog import load_products
from dashboard.demo_data import DemoDashboardDataProvider, LocalDashboardDataProvider
from dashboard.routes import DashboardRouter
from dashboard.server import CSP, create_server
from memory import (
    DecisionHistoryEntry, OwnedItem, PurchaseCondition, UserPreferences,
    WishlistItem, WishlistPriority, WishlistStatus, initialize_user_data,
    save_decision_history, save_inventory, save_preferences, save_wishlist,
)


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server(0, demo=True, project_root=ROOT)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2)

    def get(self, path):
        try:
            with urlopen(self.base + path, timeout=3) as response:
                body = response.read()
                return response.status, response.headers, body
        except HTTPError as error:
            return error.code, error.headers, error.read()

    def json(self, path):
        status, headers, body = self.get(path)
        return status, headers, json.loads(body)

    def test_server_starts_on_localhost_and_status(self) -> None:
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, headers, body = self.json("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["product_count"], 34)
        self.assertEqual(body["mode"], "DEMO")
        self.assertTrue(body["read_only"])
        self.assertEqual(headers["Content-Security-Policy"], CSP)

    def test_local_and_demo_providers_cover_full_catalog(self) -> None:
        local = LocalDashboardDataProvider(ROOT, ROOT / "missing-user-data").load()
        demo = DemoDashboardDataProvider(ROOT).load()
        self.assertEqual(len(local.products), 34)
        self.assertEqual(len(demo.products), 34)
        self.assertEqual(sum(item.used_median is not None for item in demo.products), 7)
        self.assertEqual(sum(item.used_median is not None for item in local.products), 0)

    def test_default_absent_runtime_memory_is_empty(self) -> None:
        data = LocalDashboardDataProvider(ROOT, ROOT / "does-not-exist").load()
        self.assertEqual(data.context["owned_product_ids"], [])
        self.assertEqual(data.context["active_wishlist_count"], 0)

    def test_runtime_memory_is_loaded_read_only(self) -> None:
        products = load_products(ROOT / "data" / "products.csv")
        with tempfile.TemporaryDirectory() as directory:
            user = Path(directory) / "user"
            initialize_user_data(ROOT / "data" / "templates", user)
            now = datetime(2026, 8, 1, tzinfo=timezone.utc)
            save_inventory(user / "user_inventory.csv", [OwnedItem("body", "sony-alpha-a7-iv", date(2024, 1, 1), 1000, "EUR", PurchaseCondition.USED, None, None, None, [], "***1234", "private", True)])
            save_wishlist(user / "user_wishlist.csv", [WishlistItem("wish", "sony-alpha-a7-v", 2000, "EUR", WishlistPriority.HIGH, PurchaseCondition.EITHER, None, "", WishlistStatus.ACTIVE, now, now)])
            save_decision_history(user / "user_decision_history.csv", [DecisionHistoryEntry("decision", "sony-alpha-a7-iv", "https://example.test/item?utm_source=x&id=4", "Market", "MONITOR", 70, "EQUIVALENT", 1000, "EUR", ["Safe"], "", now)])
            save_preferences(user / "user_preferences.json", UserPreferences(target_market_country="Italy"))
            before = {path.name: path.read_bytes() for path in user.iterdir()}
            data = LocalDashboardDataProvider(ROOT, user).load()
            self.assertIn("sony-alpha-a7-iv", data.context["owned_product_ids"])
            self.assertEqual(data.context["active_wishlist_count"], 1)
            self.assertEqual(before, {path.name: path.read_bytes() for path in user.iterdir()})
            serialized = json.dumps(data.context)
            self.assertNotIn("1234", serialized); self.assertNotIn("private", serialized)

    def test_product_list_is_full_and_deterministic(self) -> None:
        first = self.json("/api/products")[2]
        second = self.json("/api/products")[2]
        self.assertEqual(first, second)
        self.assertEqual(first["count"], 34)
        self.assertEqual(
            [item["display_name"] for item in first["products"]],
            sorted((item["display_name"] for item in first["products"]), key=str.casefold),
        )

    def test_detail_enriched_and_incomplete(self) -> None:
        enriched = self.json("/api/products/sony-alpha-a7-iv")[2]
        self.assertIsNotNone(enriched["market"]["used"])
        incomplete = self.json("/api/products/sony-fe-50mm-f1-8")[2]
        self.assertIsNone(incomplete["market"]["new"])
        self.assertEqual(incomplete["listings"], [])
        self.assertIsNone(incomplete["ownership"])
        self.assertTrue(incomplete["aliases"])

    def test_unknown_product_and_path_traversal(self) -> None:
        self.assertEqual(self.json("/api/products/not-real")[0], 404)
        self.assertEqual(self.json("/api/products/..%2Fsecret")[0], 400)
        self.assertEqual(self.get("/unknown.html")[0], 404)

    def test_search_alias_partial_multiple_and_no_result(self) -> None:
        alias = self.json("/api/search?q=a7iv")[2]
        self.assertEqual(alias["products"][0]["id"], "sony-alpha-a7-iv")
        partial = self.json("/api/search?q=night+walker")[2]
        self.assertEqual(partial["products"][0]["id"], "sirui-night-walker-35mm-t1-2-s35")
        multiple = self.json("/api/search?q=sony+70-200+ii")[2]
        self.assertEqual(multiple["products"][0]["id"], "sony-fe-70-200mm-f2-8-gm-oss-ii")
        self.assertEqual(self.json("/api/search?q=no-such-product")[2]["count"], 0)

    def test_version_specific_ranking(self) -> None:
        sigma = self.json("/api/search?q=sigma+24-70+ii")[2]["products"]
        self.assertEqual(sigma[0]["id"], "sigma-24-70mm-f2-8-dg-dn-ii-art")
        a7 = self.json("/api/search?q=a7+iv")[2]["products"]
        self.assertEqual(a7[0]["id"], "sony-alpha-a7-iv")

    def test_filters_and_malformed_queries(self) -> None:
        body = self.json("/api/products?category=Camera&brand=Sony&mount=sony-e")[2]
        self.assertTrue(body["products"])
        self.assertTrue(all(item["category"] == "Camera" and item["brand"] == "Sony" for item in body["products"]))
        self.assertEqual(self.json("/api/products?owned=maybe")[0], 400)
        self.assertEqual(self.json("/api/products?confidence_min=101")[0], 400)
        self.assertEqual(self.json("/api/products?sort=unknown")[0], 400)
        self.assertEqual(self.json("/api/products?extra=x")[0], 400)

    def test_unavailable_prices_sort_last_both_directions(self) -> None:
        for order in ("asc", "desc"):
            products = self.json(f"/api/products?sort=used_price&order={order}")[2]["products"]
            available = [item["used_median"] is not None for item in products]
            self.assertEqual(available, sorted(available, reverse=True))

    def test_comparison_limits_and_order(self) -> None:
        ids = "sony-alpha-a7-iv,sony-alpha-a7-v"
        body = self.json(f"/api/compare?ids={ids}")[2]
        self.assertEqual([item["id"] for item in body["products"]], ids.split(","))
        four = ids + ",panasonic-lumix-s5-ii,sony-fe-50mm-f1-4-gm"
        self.assertEqual(self.json(f"/api/compare?ids={four}")[2]["count"], 4)
        self.assertEqual(self.json(f"/api/compare?ids={four},sony-fe-50mm-f1-8")[0], 400)
        self.assertEqual(self.json("/api/compare?ids=sony-alpha-a7-iv")[0], 400)

    def test_root_and_exact_static_allowlist(self) -> None:
        status, _, body = self.get("/")
        self.assertEqual(status, 200); self.assertIn("Cerca nel catalogo".encode(), body)
        for path in ("/index.html", "/product.html", "/compare.html", "/app.js", "/product.js", "/compare.js", "/styles.css"):
            self.assertEqual(self.get(path)[0], 200)

    def test_serialization_allowlist_and_safe_browser_rendering(self) -> None:
        body = json.dumps(self.json("/api/products/sony-alpha-a7-iv")[2])
        for forbidden in ("serial_reference", "raw_data", "repair", "source file", "private"):
            self.assertNotIn(forbidden, body)
        scripts = "\n".join(path.read_text() for path in (ROOT / "web").glob("*.js"))
        self.assertNotIn("innerHTML", scripts)
        self.assertIn("textContent", scripts)
        self.assertIn('link.rel="noopener noreferrer"', (ROOT / "web" / "product.js").read_text())
        self.assertIn('!["http:","https:"]', (ROOT / "web" / "product.js").read_text())

    def test_python_39_compatibility(self) -> None:
        for path in (ROOT / "src" / "dashboard").glob("*.py"):
            ast.parse(path.read_text(), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
