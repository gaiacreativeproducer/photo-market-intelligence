"""Tests for the universal live-radar pipeline."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from catalog import load_product_aliases, load_products
from connectors.manual_url import ManualUrlConnector
from dashboard.demo_data import LocalDashboardDataProvider
from radar.importers import RadarValidationError, extract_structured_price, load_sources
from radar.models import (
    ImportedRecord, RadarRun, RadarSource, RadarWatch, RunStatus, SourceBatch,
    SourceType,
)
from radar.persistence import RadarStore
from radar.pipeline import RadarPipeline
from radar.source_registry import SourceRegistry


NOW = datetime(2026, 8, 6, 12, tzinfo=timezone.utc)


class StaticConnector:
    batches = {}

    def __init__(self, source, **kwargs):
        self.source = source

    def validate_source_configuration(self):
        if self.source.endpoint == "fail":
            raise ValueError("private source detail")

    def fetch_records(self):
        return self.batches[self.source.endpoint]

    def normalize_record(self, record):
        return dict(record.values)


class RadarTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.products = load_products(root / "data" / "products.csv")
        cls.aliases = load_product_aliases(root / "data" / "product_aliases.csv", cls.products)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.store = RadarStore(self.directory)
        self.registry = SourceRegistry()
        self.registry.register("JSON_FEED", StaticConnector)
        self.pipeline = RadarPipeline(
            self.store, self.products, self.aliases, self.registry,
            now=lambda: NOW,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def source(self, identifier="source", endpoint="batch"):
        return RadarSource(identifier, identifier, SourceType.JSON_FEED, endpoint,
                           True, "IT", "EUR", "USED", 2, 0, 60, {})

    def record(self, title="Unrelated kitchen chair", description="ordinary item",
               identifier="1"):
        return ImportedRecord({
            "external_id": identifier, "url": f"https://example.test/{identifier}",
            "title": title, "description": description, "price": 100,
            "currency": "EUR", "source_country": "IT", "segment": "USED",
        }, f"record:{identifier}")

    def execute(self, records, watches=(), errors=(), sources=None):
        StaticConnector.batches["batch"] = SourceBatch(list(records), list(errors))
        return self.pipeline.run(sources or [self.source()], watches)

    def test_unrelated_record_is_counted_but_not_persisted(self):
        result = self.execute([self.record()])
        self.assertEqual(result.run.listing_count_raw, 1)
        self.assertEqual(result.run.listing_count_normalized, 1)
        self.assertEqual(result.run.listing_count_ignored, 1)
        self.assertEqual(self.store.load_listings(), [])
        self.assertEqual(result.health[0].status, "HEALTHY")

    def test_active_watch_match_is_persisted(self):
        watch = RadarWatch("w", "", "kitchen chair", "EITHER", None, "EUR", [],
                           True, "LOW", NOW, NOW)
        result = self.execute([self.record()], [watch])
        self.assertEqual(len(result.listings), 1)
        self.assertEqual(result.listings[0].run_id, result.run.run_id)

    def test_recognized_catalog_product_is_persisted_without_watch(self):
        result = self.execute([self.record("Sony A7 IV ILCE-7M4", identifier="a7")])
        self.assertEqual(result.listings[0].product_id, "sony-alpha-a7-iv")
        self.assertGreaterEqual(result.listings[0].recognition_confidence, 70)

    def test_ambiguous_record_is_not_persisted(self):
        result = self.execute([self.record("Sony camera or Panasonic camera")])
        self.assertEqual(result.run.listing_count_ignored, 1)

    def test_privacy_is_removed_after_description_analysis(self):
        description = "circa 60k scatti email mario@example.com telefono +39 333 123 4567"
        result = self.execute([self.record("Sony A7 IV", description, "private")])
        listing = result.listings[0]
        self.assertEqual(listing.shutter_count, 60000)
        self.assertNotIn("mario@example.com", listing.description)
        self.assertNotIn("333 123 4567", listing.description)
        self.assertIn("personal data removed from persisted text", listing.warnings)

    def test_started_run_transitions_to_completed(self):
        result = self.execute([])
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertEqual(self.store.load_runs()[0].status, RunStatus.COMPLETED)

    def test_mixed_sources_are_partial_and_errors_have_run_id(self):
        StaticConnector.batches["batch"] = SourceBatch([], [])
        result = self.pipeline.run([self.source("good"), self.source("bad", "fail")], [])
        self.assertEqual(result.run.status, RunStatus.PARTIAL)
        self.assertEqual(result.errors[0].run_id, result.run.run_id)

    def test_no_successful_source_is_failed(self):
        result = self.pipeline.run([self.source("bad", "fail")], [])
        self.assertEqual(result.run.status, RunStatus.FAILED)

    def test_stale_started_run_is_recovered(self):
        old = RadarRun("old", NOW, None, RunStatus.STARTED, 1, 0, 0, 0, 0, 0, 0, 0, "")
        self.store.save_runs([old])
        self.execute([])
        runs = self.store.load_runs()
        self.assertEqual(runs[0].status, RunStatus.FAILED)
        self.assertTrue(any(error.run_id == "old" for error in self.store.load_errors()))

    def test_dry_run_never_persists(self):
        StaticConnector.batches["batch"] = SourceBatch([self.record("Sony A7 IV")], [])
        result = self.pipeline.run([self.source()], [], dry_run=True)
        self.assertEqual(result.run.status, RunStatus.DRY_RUN)
        self.assertEqual(self.store.load_runs(), [])
        self.assertEqual(self.store.load_listings(), [])

    def test_row_error_is_isolated(self):
        result = self.execute([self.record("Sony A7 IV")], errors=["row 3 invalid"])
        self.assertEqual(len(result.listings), 1)
        self.assertEqual(len(result.errors), 1)

    def test_local_smoke_pipeline_and_dashboard(self):
        manual_path = self.directory / "manual.csv"
        manual_path.write_text(
            "manual_id,url,source_name,title,description,price,currency,source_country,segment,detected_at,active\n"
            "subito-1,https://www.subito.it/fotografia/sony-a7-iv,Subito,Sony A7 IV,"
            "60k scatti contatto seller@example.com tel +39 333 123 4567,1100,EUR,IT,USED,,true\n",
            encoding="utf-8",
        )
        registry = SourceRegistry()
        registry.register("JSON_FEED", StaticConnector)
        registry.register("MANUAL_URL", ManualUrlConnector)
        StaticConnector.batches["batch"] = SourceBatch([
            self.record("Sony A7 IV", identifier="feed-relevant"),
            self.record(identifier="feed-unrelated"),
        ], [])
        pipeline = RadarPipeline(
            self.store, self.products, self.aliases, registry,
            user_directory=self.directory, now=lambda: NOW,
        )
        manual = RadarSource("manual", "Manual Subito", SourceType.MANUAL_URL,
                             "manual.csv", True, "IT", "EUR", "USED", 2, 0, 60, {})
        result = pipeline.run([
            self.source("healthy"), self.source("malformed", "fail"), manual,
        ], [])
        self.assertEqual(result.run.status, RunStatus.PARTIAL)
        self.assertEqual(result.run.listing_count_ignored, 1)
        self.assertEqual(len(result.listings), 2)
        persisted_subito = next(item for item in result.listings if item.source_id == "manual")
        self.assertEqual(persisted_subito.shutter_count, 60000)
        self.assertNotIn("seller@example.com", persisted_subito.description)
        self.assertNotIn("333 123 4567", persisted_subito.description)
        dashboard = LocalDashboardDataProvider(PROJECT_ROOT, self.directory).load()
        self.assertEqual(dashboard.context["latest_radar_status"], "PARTIAL")
        self.assertEqual(dashboard.context["latest_radar_ignored_count"], 1)
        self.assertEqual(dashboard.context["live_listing_count"], 2)
        detail_text = json.dumps(dashboard.details["sony-alpha-a7-iv"]["listings"])
        self.assertNotIn("seller@example.com", detail_text)


class ImporterTests(unittest.TestCase):
    def test_price_regex_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "sources.json"
            source = _source_config()
            source["mapping"] = {"price_regex": "(.*)+"}
            path.write_text(json.dumps({"sources": [source]}), encoding="utf-8")
            with self.assertRaisesRegex(RadarValidationError, "price_regex"):
                load_sources(path)

    def test_structured_price_extraction_is_deterministic(self):
        config = {"currency_symbol": "€", "currency_code": "EUR",
                  "decimal_separator": ",", "thousands_separator": ".",
                  "allowed_prefixes": ["price"], "allowed_suffixes": []}
        self.assertEqual(extract_structured_price("price € 1.234,50", config), 1234.5)
        with self.assertRaises(ValueError):
            extract_structured_price("ordinary prose 1234", config)

    def test_manual_records_are_active_explicit_and_deduplicated_without_http(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / "manual.csv"
            path.write_text(
                "manual_id,url,source_name,title,description,price,currency,source_country,segment,detected_at,active\n"
                "one,https://www.subito.it/a?utm_source=x,Subito,Sony A7 IV,Test,900,EUR,IT,USED,,true\n"
                "one,https://www.subito.it/a,Subito,Sony A7 IV,Test,900,EUR,IT,USED,,true\n"
                "off,https://www.subito.it/off,Subito,Off,Test,10,EUR,IT,USED,,false\n",
                encoding="utf-8",
            )
            source = RadarSource("manual", "Manual", SourceType.MANUAL_URL,
                                 "manual.csv", True, "IT", "EUR", "USED", 1, 0, 60, {})
            batch = ManualUrlConnector(source, user_directory=root).fetch_records()
            self.assertEqual(len(batch.records), 1)
            self.assertTrue(batch.records[0].explicitly_supplied)


def _source_config():
    return {
        "source_id": "test", "name": "Test", "source_type": "JSON_FEED",
        "endpoint": "https://example.test/feed", "enabled": True,
        "country": "IT", "currency": "EUR", "segment": "USED",
        "request_timeout_seconds": 2, "retry_count": 0,
        "minimum_request_interval_seconds": 60, "mapping": {}, "notes": "",
    }


if __name__ == "__main__":
    unittest.main()
