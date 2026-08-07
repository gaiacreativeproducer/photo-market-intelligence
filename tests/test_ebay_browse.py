"""Deterministic tests for the official eBay Browse connector."""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catalog import load_product_aliases, load_products
from connectors.ebay_auth import EbayAuth
from connectors.ebay_browse import EbayBrowseConnector
from connectors.models import ConnectorError, SearchQuery
from dashboard.routes import DashboardRouter
from dashboard.demo_data import DemoDashboardDataProvider
from dashboard.demo_data import LocalDashboardDataProvider
from radar.importers import RadarValidationError, load_sources
from radar.models import RadarSource, RadarWatch, SourceType
from radar.models import ImportedRecord, SourceBatch
from radar.persistence import RadarStore
from radar.pipeline import RadarPipeline
from radar.source_registry import SourceRegistry
from market.engine import MarketEngine
from market.models import ExclusionReason


class Response:
    def __init__(self, value, status=200):
        self.body = json.dumps(value).encode("utf-8")
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit=-1): return self.body[:limit] if limit >= 0 else self.body


class QueueOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=0):
        self.requests.append((request, timeout))
        value = self.responses.pop(0)
        if isinstance(value, Exception): raise value
        return value


def item(identifier="v1|123|0", title="Sony A7 IV ILCE-7M4", condition="Used", condition_id="3000", buying=None):
    return {
        "itemId": identifier, "title": title,
        "itemWebUrl": "https://www.ebay.it/itm/123",
        "price": {"value": "1200.00", "currency": "EUR"},
        "condition": condition, "conditionId": condition_id,
        "buyingOptions": buying or ["FIXED_PRICE"],
        "itemLocation": {"country": "DE"},
        "shippingOptions": [{"shippingCost": {"value": "18.50", "currency": "EUR"}}],
        "shortDescription": "60000 scatti, scatola e fattura",
    }


def source(**changes):
    values = dict(
        source_id="ebay-it", name="eBay Italia", source_type=SourceType.EBAY_BROWSE,
        endpoint="", enabled=True, country="IT", currency="EUR", segment="EITHER",
        request_timeout_seconds=15, retry_count=1,
        minimum_request_interval_seconds=0, mapping={}, notes="",
        marketplace_id="EBAY_IT", query_limit=50,
    )
    values.update(changes)
    return RadarSource(**values)


class EbayAuthTests(unittest.TestCase):
    def test_token_request_cache_and_refresh(self):
        now = [100.0]
        opener = QueueOpener(
            Response({"access_token": "first", "expires_in": 120}),
            Response({"access_token": "second", "expires_in": 120}),
        )
        auth = EbayAuth("client", "secret", "SANDBOX", opener, lambda: now[0])
        self.assertEqual(auth.access_token(), "first")
        self.assertEqual(auth.access_token(), "first")
        self.assertEqual(len(opener.requests), 1)
        request = opener.requests[0][0]
        self.assertEqual(request.full_url, "https://api.sandbox.ebay.com/identity/v1/oauth2/token")
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        self.assertIn(b"grant_type=client_credentials", request.data)
        now[0] = 170.0
        self.assertEqual(auth.access_token(), "second")

    def test_production_host_and_invalid_credentials(self):
        opener = QueueOpener(Response({"access_token": "token", "expires_in": 120}))
        auth = EbayAuth("client", "secret", "PRODUCTION", opener)
        auth.access_token()
        self.assertIn("https://api.ebay.com/", opener.requests[0][0].full_url)
        with self.assertRaisesRegex(ConnectorError, "credentials are not configured"):
            EbayAuth("", "", "SANDBOX").access_token()


class EbayConnectorTests(unittest.TestCase):
    def auth(self, environment="SANDBOX"):
        auth = EbayAuth("client", "secret", environment)
        auth._token = type("Token", (), {"value": "safe-token", "expires_at": 99999999999.0})()
        return auth

    def test_search_headers_query_and_normalization(self):
        opener = QueueOpener(Response({"itemSummaries": [item()]}))
        connector = EbayBrowseConnector(source(), auth=self.auth(), opener=opener, sleep_func=lambda _: None)
        result = connector.search(SearchQuery("Sony A7 IV", 50))[0]
        request = opener.requests[0][0]
        self.assertIn("q=Sony+A7+IV", request.full_url)
        self.assertEqual(request.get_header("X-ebay-c-marketplace-id"), "EBAY_IT")
        self.assertEqual(result.external_id, "v1|123|0")
        self.assertEqual(result.price, 1200.0)
        self.assertEqual(result.shipping_cost, 18.5)
        self.assertEqual(result.item_location_country, "DE")
        self.assertTrue(result.market_stats_eligible)

    def test_condition_and_auction_mapping(self):
        opener = QueueOpener(Response({"itemSummaries": [
            item("new", condition="New", condition_id="1000"),
            item("auction", condition="Seller refurbished", condition_id="2500", buying=["AUCTION"]),
        ]}))
        results = EbayBrowseConnector(source(), auth=self.auth(), opener=opener, sleep_func=lambda _: None).search(SearchQuery("camera", 2))
        self.assertEqual(results[0].raw_data["segment"], "NEW")
        self.assertEqual(results[1].raw_data["segment"], "USED")
        self.assertEqual(results[1].original_condition, "Seller refurbished")
        self.assertFalse(results[1].market_stats_eligible)

    def test_auction_is_visible_but_excluded_from_primary_statistics(self):
        opener = QueueOpener(Response({"itemSummaries": [item("auction", buying=["AUCTION"])]}))
        listing = EbayBrowseConnector(source(), auth=self.auth(), opener=opener, sleep_func=lambda _: None).search(SearchQuery("camera", 1))[0]
        product = next(value for value in load_products(ROOT / "data/products.csv") if value.id == "sony-alpha-a7-iv")
        snapshot = MarketEngine(
            "DE", "EUR", "USED",
            recognized_product_ids={listing.external_id: product.id},
            recognition_confidence={listing.external_id: 100},
            description_confidence={listing.external_id: 80},
            listing_segments={listing.external_id: "USED"},
            source_countries={listing.external_id: "DE"},
            warranty_clarity={listing.external_id: False},
            accessory_completeness={listing.external_id: True},
            statistical_eligibility={listing.external_id: listing.market_stats_eligible},
        ).build_snapshot(product, [listing])
        self.assertEqual(snapshot.sample_size, 1)
        self.assertEqual(snapshot.valid_sample_size, 0)
        self.assertEqual(snapshot.observations[0].excluded_reason, ExclusionReason.UNSUPPORTED_BUYING_OPTION)

    def test_pagination_limit_and_duplicate_item(self):
        first = {"itemSummaries": [item("one")], "next": "next"}
        second = {"itemSummaries": [item("two")]}
        opener = QueueOpener(Response(first), Response(second))
        connector = EbayBrowseConnector(source(query_limit=2), auth=self.auth(), opener=opener, sleep_func=lambda _: None)
        records = connector.fetch_records_for(
            [type("Watch", (), {"active": True, "source_ids": [], "product_id": "", "query": "Sony A7 IV"})()], [], []
        ).records
        self.assertEqual({value.values["external_id"] for value in records}, {"one", "two"})
        self.assertEqual(len(opener.requests), 2)

    def test_primary_query_uses_at_most_one_fallback(self):
        products = load_products(ROOT / "data/products.csv")
        aliases = load_product_aliases(ROOT / "data/product_aliases.csv", products)
        opener = QueueOpener(Response({"itemSummaries": []}), Response({"itemSummaries": [item()]}))
        connector = EbayBrowseConnector(source(), products, aliases, auth=self.auth(), opener=opener, sleep_func=lambda _: None)
        watch = type("Watch", (), {"active": True, "source_ids": [], "product_id": "sony-alpha-a7-iv", "query": ""})()
        self.assertEqual(len(connector.fetch_records_for([watch], products, aliases).records), 1)
        self.assertEqual(len(opener.requests), 2)

    def test_rate_limit_retry_and_production_authorization(self):
        headers = Message(); headers["Retry-After"] = "2"
        rate = HTTPError("https://api.sandbox.ebay.com", 429, "rate", headers, io.BytesIO(b"{}"))
        delays = []
        opener = QueueOpener(rate, Response({"itemSummaries": []}))
        EbayBrowseConnector(source(), auth=self.auth(), opener=opener, sleep_func=delays.append).search(SearchQuery("camera", 1))
        self.assertEqual(delays, [2.0])
        denied = HTTPError("https://api.ebay.com", 403, "denied", Message(), io.BytesIO(b"{}"))
        connector = EbayBrowseConnector(source(retry_count=0), auth=self.auth("PRODUCTION"), opener=QueueOpener(denied), sleep_func=lambda _: None)
        with self.assertRaisesRegex(ConnectorError, "Production Browse access is not enabled") as context:
            connector.search(SearchQuery("camera", 1))
        self.assertEqual(context.exception.error_type, "authorization")

    def test_get_item_is_lazy(self):
        opener = QueueOpener(Response({"itemSummaries": []}), Response({"itemId": "abc"}))
        connector = EbayBrowseConnector(source(), auth=self.auth(), opener=opener, sleep_func=lambda _: None)
        connector.search(SearchQuery("camera", 1))
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(connector.get_item("abc")["itemId"], "abc")

    def test_secrets_are_not_in_listing_or_error(self):
        opener = QueueOpener(Response({"itemSummaries": [item()]}))
        result = EbayBrowseConnector(source(), auth=self.auth(), opener=opener, sleep_func=lambda _: None).search(SearchQuery("camera", 1))[0]
        serialized = json.dumps(result.raw_data)
        self.assertNotIn("safe-token", serialized)
        self.assertNotIn("client", serialized)


class EbayIntegrationTests(unittest.TestCase):
    def test_strict_source_configuration(self):
        config = {"sources": [{"source_id":"ebay-it","name":"eBay Italia","source_type":"EBAY_BROWSE","enabled":False,"marketplace_id":"EBAY_IT","country":"IT","currency":"EUR","query_limit":50,"minimum_request_interval_seconds":5}]}
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "sources.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            loaded = load_sources(path)[0]
            self.assertEqual(loaded.query_limit, 50)
            self.assertEqual(loaded.segment, "EITHER")
            config["sources"][0]["secret"] = "forbidden"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(RadarValidationError, "unknown key 'secret'"):
                load_sources(path)

    def test_radar_recognition_dedup_and_mutable_update(self):
        products = load_products(ROOT / "data/products.csv")
        aliases = load_product_aliases(ROOT / "data/product_aliases.csv", products)
        values = item()
        normalized = {
            "external_id": values["itemId"], "url": values["itemWebUrl"],
            "title": values["title"], "description": values["shortDescription"],
            "price": 1200, "currency": "EUR", "source_country": "IT",
            "segment": "USED", "condition": "Used", "marketplace_id": "EBAY_IT",
            "original_condition": "Used", "buying_options": ["FIXED_PRICE"],
            "shipping_cost": 18.5, "shipping_currency": "EUR",
            "item_location_country": "IT", "market_stats_eligible": True,
        }
        class Adapter:
            def __init__(self, source, **kwargs): self.source = source
            def validate_source_configuration(self): pass
            def fetch_records_for(self, watches, products, aliases): return SourceBatch([ImportedRecord(dict(normalized), "ebay-item")])
            def normalize_record(self, record): return record.values
        registry = SourceRegistry(); registry.register("EBAY_BROWSE", Adapter)
        with tempfile.TemporaryDirectory() as name:
            store = RadarStore(Path(name))
            pipeline = RadarPipeline(store, products, aliases, registry)
            first = pipeline.run([source()], [])
            normalized["price"] = 1150
            second = pipeline.run([source()], [])
            self.assertEqual(len(second.listings), 1)
            self.assertEqual(second.listings[0].product_id, "sony-alpha-a7-iv")
            self.assertEqual(second.listings[0].price, 1150)
            self.assertEqual(second.listings[0].first_seen_at, first.listings[0].first_seen_at)

    def test_production_shaped_results_keep_accessory_out_of_workspace_and_market(self):
        fixture = json.loads(
            (ROOT / "tests/fixtures/ebay_search_production.json").read_text(encoding="utf-8")
        )
        products = load_products(ROOT / "data/products.csv")
        aliases = load_product_aliases(ROOT / "data/product_aliases.csv", products)
        opener = QueueOpener(Response(fixture))
        auth = EbayAuth("client", "secret", "SANDBOX")
        auth._token = type("Token", (), {"value": "safe-token", "expires_at": 99999999999.0})()
        class Adapter(EbayBrowseConnector):
            def __init__(self, radar_source, **kwargs):
                super().__init__(radar_source, auth=auth, opener=opener, sleep_func=lambda _: None, **kwargs)
        registry = SourceRegistry(); registry.register("EBAY_BROWSE", Adapter)
        now = datetime(2026, 8, 7, tzinfo=timezone.utc)
        watch = RadarWatch(
            "a7", "sony-alpha-a7-iv", "Sony A7 IV", "EITHER", None, "EUR",
            ["ebay-it"], True, "HIGH", now, now,
        )
        with tempfile.TemporaryDirectory() as name:
            runtime = Path(name)
            result = RadarPipeline(
                RadarStore(runtime), products, aliases, registry, now=lambda: now
            ).run([source(query_limit=10)], [watch])
            self.assertEqual(result.run.listing_count_raw, 3)
            self.assertEqual(result.recognized_count, 2)
            self.assertEqual(result.persisted_relevant_count, 2)
            self.assertEqual(result.ignored_accessory_unmatched_count, 1)
            self.assertEqual(result.needs_review_count, 0)
            self.assertEqual(len(result.listings), 2)
            self.assertNotIn("housing", " ".join(item.title.casefold() for item in result.listings))
            dashboard = LocalDashboardDataProvider(ROOT, runtime).load()
            workspace = dashboard.details["sony-alpha-a7-iv"]["workspace"]
            self.assertEqual(workspace.offer_count, 2)
            prices = {item["price"] for item in workspace.active_offers}
            self.assertEqual(prices, {1499.0, 1549.0})
            self.assertNotIn(399.0, prices)
            market_medians = {
                snapshot["median"] for snapshot in workspace.market_snapshots.values()
            }
            self.assertEqual(market_medians, {1499.0, 1549.0})
            self.assertNotIn(399.0, market_medians)

    def test_refresh_route_success_and_errors(self):
        provider = DemoDashboardDataProvider(ROOT, Path(tempfile.mkdtemp()))
        data = provider.load()
        class Refresh:
            def refresh(self, product_id):
                return {"environment":"SANDBOX","retrieved":3,"recognized":2,"persisted_relevant":2,"ignored_accessory_unmatched":1,"needs_review":0,"results_retrieved":3,"relevant_offers_added":2,"existing_offers_updated":0,"ignored_results":1,"connector_errors":[],"status":"COMPLETED"}
        router = DashboardRouter(data, ROOT / "web", ebay_refresh_service=Refresh(), data_loader=lambda: data)
        status, _, body = router.dispatch_post("/api/products/sony-alpha-a7-iv/ebay-refresh", {})
        self.assertEqual(status, 200)
        response = json.loads(body)
        self.assertEqual(response["environment"], "SANDBOX")
        self.assertEqual(response["ignored_accessory_unmatched"], 1)
        status, _, _ = router.dispatch_post("/api/products/sony-alpha-a7-iv/ebay-refresh", {"extra": True})
        self.assertEqual(status, 400)

    def test_python_39_and_no_secret_config(self):
        for path in (ROOT / "src/connectors").glob("ebay_*.py"):
            ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 9))
        example = (ROOT / "config/ebay.env.example").read_text(encoding="utf-8")
        self.assertEqual(example, "PMI_EBAY_CLIENT_ID=\nPMI_EBAY_CLIENT_SECRET=\nPMI_EBAY_ENVIRONMENT=SANDBOX\n")

    def test_connection_script_debug_output_is_complete_and_sanitized(self):
        path = ROOT / "scripts/test_ebay_connection.py"
        specification = importlib.util.spec_from_file_location("ebay_connection_script", path)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        class Auth:
            environment = "SANDBOX"
            api_root = "https://api.sandbox.ebay.com"
        class Connector:
            last_http_status = 200
            def __init__(self, auth): pass
            def search(self, query):
                return [SimpleNamespace(title=f"Title {index}", price=100 + index, currency="EUR", url=f"https://www.ebay.it/itm/{index}") for index in range(1, 4)]
        module.EbayAuth = Auth
        module.EbayBrowseConnector = Connector
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(module.main(["--debug"]), 0)
        value = output.getvalue()
        for expected in ("Endpoint: https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search", "Marketplace: EBAY_IT", "Query: Sony A7 IV", "q=Sony A7 IV", "limit=3", "offset=0", "HTTP status: 200", "Title 1", "101 EUR", "https://www.ebay.it/itm/1"):
            self.assertIn(expected, value)
        self.assertNotIn("Bearer", value)
        self.assertNotIn("OAuth", value)


if __name__ == "__main__":
    unittest.main()
