"""Tests for deterministic Market Intelligence V1."""

from __future__ import annotations

import ast
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from catalog import Product
from connectors.models import Listing, ListingDefect
from market import ExclusionReason, MarketEngine, listing_quality
from market.cleaning import MarketEvidence
from market.statistics import calculate_price_statistics, iqr_fences


class MarketIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        self.product = Product(
            "sony-alpha-a7-iv", "Camera", "Mirrorless", "Sony", "Alpha A7",
            "IV", "sony-e", 2021, None, None, None, None, None, None, None,
            "Full-frame mirrorless camera",
        )

    def test_basic_market_statistics(self) -> None:
        stats = calculate_price_statistics([10, 20, 30, 40, 50])
        self.assertEqual(stats.median, 30)
        self.assertEqual(stats.mean, 30)
        self.assertEqual(stats.trimmed_mean, 30)
        self.assertEqual(stats.minimum, 10)
        self.assertEqual(stats.maximum, 50)
        self.assertEqual(stats.percentile_10, 14)
        self.assertEqual(stats.percentile_25, 20)
        self.assertEqual(stats.percentile_75, 40)
        self.assertEqual(stats.percentile_90, 46)

    def test_trimmed_mean_removes_ten_percent_from_each_end(self) -> None:
        values = [0] + [10] * 8 + [100]
        self.assertEqual(calculate_price_statistics(values).mean, 18)
        self.assertEqual(calculate_price_statistics(values).trimmed_mean, 10)

    def test_iqr_outlier_is_excluded_but_visible(self) -> None:
        listings = [
            self.listing(str(index), price, days_ago=index)
            for index, price in enumerate([1000, 1010, 1020, 1030, 1040, 1050, 1060, 5000])
        ]
        snapshot = self.engine(listings).build_snapshot(self.product, listings)
        self.assertEqual(snapshot.outlier_count, 1)
        self.assertEqual(snapshot.sample_size, 8)
        self.assertEqual(snapshot.valid_sample_size, 7)
        outlier = next(
            item for item in snapshot.observations
            if item.excluded_reason == ExclusionReason.OUTLIER
        )
        self.assertEqual(outlier.listed_price, 5000)
        self.assertFalse(outlier.included_in_statistics)
        self.assertEqual(snapshot.highest_price, 1060)

    def test_small_sample_has_no_statistical_outlier(self) -> None:
        listings = [self.listing(str(index), value) for index, value in enumerate([10, 11, 1000])]
        snapshot = self.engine(listings).build_snapshot(self.product, listings)
        self.assertEqual(snapshot.outlier_count, 0)
        self.assertEqual(snapshot.valid_sample_size, 3)
        self.assertIsNone(iqr_fences([10, 11, 1000]))

    def test_duplicate_exclusion_uses_deterministic_priority(self) -> None:
        early = self.listing("early", 1000, country="China", days_ago=2, url="same")
        rich = self.listing("rich", 1000, country="China", days_ago=1, url="same")
        weak = self.listing("weak", 1000, country="China", days_ago=3, url="same")
        listings = [weak, rich, early]
        engine = self.engine(
            listings,
            countries={item.external_id: "China" for item in listings},
            landed={"early": 1200, "rich": 1200},
            description_evidence={"early": 5, "rich": 8, "weak": 20},
            description_confidence={"early": 100, "rich": 100, "weak": 100},
        )
        snapshot = engine.build_snapshot(self.product, listings)
        kept = [item.listing_id for item in snapshot.observations if item.included_in_statistics]
        self.assertEqual(kept, ["rich"])
        discarded = [
            item for item in snapshot.observations
            if item.excluded_reason == ExclusionReason.DUPLICATE
        ]
        self.assertEqual({item.listing_id for item in discarded}, {"early", "weak"})

    def test_wrong_currency_is_preserved_and_excluded(self) -> None:
        listing = self.listing("usd", 1000, currency="USD")
        observation = self.engine([listing]).build_snapshot(self.product, [listing]).observations[0]
        self.assertEqual(observation.excluded_reason, ExclusionReason.WRONG_CURRENCY)
        self.assertEqual(observation.listed_price, 1000)

    def test_mixed_currencies_are_never_combined(self) -> None:
        euro = self.listing("eur", 1000)
        dollar = self.listing("usd", 900, currency="USD")
        snapshot = self.engine([euro, dollar]).build_snapshot(
            self.product, [euro, dollar]
        )
        self.assertEqual(snapshot.sample_size, 2)
        self.assertEqual(snapshot.valid_sample_size, 1)
        self.assertEqual(snapshot.median_price, 1000)
        self.assertEqual(
            next(item for item in snapshot.observations if item.listing_id == "usd").excluded_reason,
            ExclusionReason.WRONG_CURRENCY,
        )

    def test_unknown_product_is_excluded(self) -> None:
        listing = self.listing("unknown", 1000)
        engine = self.engine([listing], product_ids={"unknown": "another-product"})
        observation = engine.build_snapshot(self.product, [listing]).observations[0]
        self.assertEqual(observation.excluded_reason, ExclusionReason.PRODUCT_NOT_CONFIRMED)

    def test_segment_evidence_missing_and_mismatch(self) -> None:
        missing = self.listing("missing", 1000, condition="Pari al nuovo")
        mismatch = self.listing("mismatch", 1100)
        engine = self.engine([missing, mismatch], segments={"mismatch": "NEW"})
        snapshot = engine.build_snapshot(self.product, [missing, mismatch])
        reasons = {item.listing_id: item.excluded_reason for item in snapshot.observations}
        self.assertEqual(reasons["missing"], ExclusionReason.INSUFFICIENT_INFORMATION)
        self.assertEqual(reasons["mismatch"], ExclusionReason.SEGMENT_MISMATCH)
        self.assertNotEqual(snapshot.observations[0].segment, "NEW")

    def test_domestic_eu_and_chinese_sources_are_metadata(self) -> None:
        listings = [
            self.listing("it", 1000, country="Italy"),
            self.listing("de", 1050, country="Germany"),
            self.listing("cn", 900, country="China"),
        ]
        countries = {"it": "Italy", "de": "Germany", "cn": "China"}
        engine = self.engine(
            listings, countries=countries, landed={"de": 1120, "cn": 1150}
        )
        snapshot = engine.build_snapshot(self.product, listings)
        self.assertEqual(snapshot.source_countries, ["China", "Germany", "Italy"])
        self.assertEqual(snapshot.valid_sample_size, 3)

    def test_foreign_landed_cost_rules(self) -> None:
        listing = self.listing("foreign", 900, country="China")
        excluded = self.engine(
            [listing], countries={"foreign": "China"}
        ).build_snapshot(self.product, [listing]).observations[0]
        self.assertIsNone(excluded.landed_cost_estimate)
        self.assertIsNone(excluded.statistical_price)
        self.assertEqual(excluded.excluded_reason, ExclusionReason.LANDED_COST_UNKNOWN)

        included = self.engine(
            [listing], countries={"foreign": "China"}, landed={"foreign": 1150}
        ).build_snapshot(self.product, [listing]).observations[0]
        self.assertTrue(included.included_in_statistics)
        self.assertEqual(included.landed_cost_estimate, 1150)
        self.assertEqual(included.statistical_price, 1150)

    def test_country_diversity_does_not_raise_confidence(self) -> None:
        domestic = [self.listing(str(index), 1000 + index, days_ago=index) for index in range(8)]
        diverse = [replace(item, external_id=f"d{index}") for index, item in enumerate(domestic)]
        domestic_snapshot = self.engine(domestic).build_snapshot(self.product, domestic)
        countries = {
            item.external_id: ("Germany" if index % 2 else "Italy")
            for index, item in enumerate(diverse)
        }
        landed = {
            item.external_id: item.price
            for item in diverse if countries[item.external_id] != "Italy"
        }
        diverse_snapshot = self.engine(
            diverse, countries=countries, landed=landed
        ).build_snapshot(self.product, diverse)
        self.assertEqual(domestic_snapshot.market_confidence, diverse_snapshot.market_confidence)

    def test_multiple_countries_with_unknown_landed_cost_add_note(self) -> None:
        domestic = self.listing("it", 1000)
        foreign = self.listing("cn", 900, country="China")
        snapshot = self.engine(
            [domestic, foreign], countries={"it": "Italy", "cn": "China"}
        ).build_snapshot(self.product, [domestic, foreign])
        self.assertTrue(any("not normalized" in note for note in snapshot.notes))

    def test_listing_quality_and_honest_defect_disclosure(self) -> None:
        clean = self.listing("clean", 1000)
        disclosed = replace(clean, defects=[ListingDefect(
            "scratches", "Visible body scratch", "minor", "body",
            "Visible body scratch", 1.0,
        )])
        evidence = self.evidence([clean])
        self.assertEqual(listing_quality(clean, evidence), 100)
        self.assertEqual(listing_quality(disclosed, evidence), 100)
        unknown = replace(clean, condition="Unknown")
        self.assertEqual(listing_quality(unknown, evidence), 85)
        contradictory = replace(clean, external_id="contradictory")
        contradictory_evidence = self.evidence(
            [contradictory], contradictions={"contradictory": True}
        )
        self.assertEqual(listing_quality(contradictory, contradictory_evidence), 75)
        self.assertEqual(listing_quality(replace(clean, price=None), evidence), 0)

    def test_severe_damage_is_excluded_but_preserved(self) -> None:
        listing = replace(self.listing("damaged", 500), defects=[ListingDefect(
            "cracks", "Cracked front element", "critical", "front element",
            "Cracked front element", 1.0,
        )])
        snapshot = self.engine([listing]).build_snapshot(self.product, [listing])
        observation = snapshot.observations[0]
        self.assertEqual(observation.excluded_reason, ExclusionReason.SEVERE_DAMAGE)
        self.assertEqual(observation.listing_quality, 100)

    def test_market_confidence_and_temporal_coverage(self) -> None:
        listings = [self.listing(str(index), 1000 + index, days_ago=index) for index in range(21)]
        snapshot = self.engine(listings).build_snapshot(self.product, listings)
        self.assertEqual(snapshot.market_confidence, 100)
        tiny = listings[:1]
        tiny_confidence = self.engine(tiny).build_snapshot(
            self.product, tiny
        ).market_confidence
        self.assertEqual(tiny_confidence, 53)
        self.assertLess(tiny_confidence, snapshot.market_confidence)

    def test_no_history_has_no_trends_or_depreciation(self) -> None:
        listings = self.market_listings(1000)
        snapshot = self.engine(listings).build_snapshot(self.product, listings)
        self.assertIsNone(snapshot.trend_30d)
        self.assertIsNone(snapshot.trend_90d)
        self.assertIsNone(snapshot.trend_180d)
        self.assertIsNone(snapshot.estimated_12_month_depreciation)
        self.assertIsNone(snapshot.estimated_24_month_depreciation)

    def test_exact_12_and_24_month_depreciation(self) -> None:
        current_listings = self.market_listings(900)
        year_listings = self.market_listings(1000, prefix="year")
        two_year_listings = self.market_listings(1200, prefix="two")
        year = self.engine(
            year_listings, created_at=self.now - timedelta(days=365)
        ).build_snapshot(self.product, year_listings)
        two_year = self.engine(
            two_year_listings, created_at=self.now - timedelta(days=730)
        ).build_snapshot(self.product, two_year_listings)
        current = self.engine(
            current_listings, history=[year, two_year], created_at=self.now
        ).build_snapshot(self.product, current_listings)
        self.assertAlmostEqual(current.estimated_12_month_depreciation, 10)
        self.assertAlmostEqual(current.estimated_24_month_depreciation, 25)

    def test_depreciation_tolerance_and_confidence(self) -> None:
        current_listings = self.market_listings(900)
        old_listings = self.market_listings(1000, prefix="old")
        outside = self.engine(
            old_listings, created_at=self.now - timedelta(days=411)
        ).build_snapshot(self.product, old_listings)
        low = replace(outside, created_at=self.now - timedelta(days=365), market_confidence=39)
        for history in ([outside], [low]):
            with self.subTest(history=history[0].created_at):
                current = self.engine(
                    current_listings, history=history, created_at=self.now
                ).build_snapshot(self.product, current_listings)
                self.assertIsNone(current.estimated_12_month_depreciation)

    def test_trend_exact_and_outside_tolerance(self) -> None:
        current_listings = self.market_listings(1100)
        old_listings = self.market_listings(1000, prefix="old")
        exact = self.engine(
            old_listings, created_at=self.now - timedelta(days=30)
        ).build_snapshot(self.product, old_listings)
        current = self.engine(
            current_listings, history=[exact], created_at=self.now
        ).build_snapshot(self.product, current_listings)
        self.assertAlmostEqual(current.trend_30d, 10)
        outside = replace(exact, created_at=self.now - timedelta(days=41))
        unavailable = self.engine(
            current_listings, history=[outside], created_at=self.now
        ).build_snapshot(self.product, current_listings)
        self.assertIsNone(unavailable.trend_30d)
        self.assertIsNone(unavailable.trend_90d)

    def test_sources_parse_as_python_3_9(self) -> None:
        for source_path in (PROJECT_ROOT / "src" / "market").glob("*.py"):
            with self.subTest(source=source_path.name):
                ast.parse(source_path.read_text(), feature_version=(3, 9))

    def engine(
        self, listings, countries=None, landed=None, segments=None,
        product_ids=None, description_evidence=None,
        description_confidence=None, history=None, created_at=None,
    ) -> MarketEngine:
        evidence = self.evidence(
            listings,
            countries=countries,
            landed=landed,
            segments=segments,
            product_ids=product_ids,
            description_evidence=description_evidence,
            description_confidence=description_confidence,
        )
        return MarketEngine(
            "Italy", "EUR", "USED",
            recognized_product_ids=evidence.recognized_product_ids,
            recognition_confidence=evidence.recognition_confidence,
            description_confidence=evidence.description_confidence,
            description_contradictions=evidence.description_contradictions,
            description_evidence_count=evidence.description_evidence_count,
            listing_segments=evidence.listing_segments,
            source_countries=evidence.source_countries,
            landed_costs=evidence.landed_costs,
            warranty_clarity=evidence.warranty_clarity,
            accessory_completeness=evidence.accessory_completeness,
            history=history,
            created_at=created_at or self.now,
        )

    def evidence(
        self, listings, countries=None, landed=None, segments=None,
        product_ids=None, description_evidence=None,
        description_confidence=None, contradictions=None,
    ) -> MarketEvidence:
        ids = [listing.external_id for listing in listings]
        return MarketEvidence(
            product_ids or {item: self.product.id for item in ids},
            {item: 100 for item in ids},
            description_confidence or {item: 100 for item in ids},
            contradictions or {},
            description_evidence or {item: 5 for item in ids},
            segments if segments is not None else {item: "USED" for item in ids},
            countries or {item: "Italy" for item in ids},
            landed or {},
            {item: True for item in ids},
            {item: True for item in ids},
        )

    def market_listings(self, base_price: float, prefix: str = "current"):
        return [
            self.listing(
                f"{prefix}-{index}", base_price + (index - 4.5) * 2,
                days_ago=index,
            )
            for index in range(10)
        ]

    def listing(
        self, listing_id: str, price: float, days_ago: int = 0,
        currency: str = "EUR", country: str = "Italy",
        condition: str = "Used", url: str = "",
    ) -> Listing:
        return Listing(
            listing_id, "test", f"Sony A7 IV {listing_id}",
            url or f"https://example.invalid/{listing_id}", price, currency,
            condition, country, "seller", "Detailed honest description",
            self.now - timedelta(days=days_ago), {}, "test",
        )


if __name__ == "__main__":
    unittest.main()
