"""Tests for Explainable Decision Engine V1."""

from __future__ import annotations

import ast
import sys
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from catalog import Product
from connectors.models import Listing, ListingDefect
from decision import DecisionEngine, MarketStatistics, NewAlternative, Recommendation


class DecisionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DecisionEngine(as_of=date(2026, 4, 1))

    def test_clean_used_bargain(self) -> None:
        report = self.engine.evaluate(
            self.product(liquidity_score=85),
            self.listing(price=1000, shutter_count=8_000, warranty_until="2027-04-30"),
            self.market(median_used_price=1400),
        )
        self.assertEqual(report.recommendation, Recommendation.BUY_USED)
        self.assertGreaterEqual(report.buy_score, 75)

    def test_price_close_to_new_recommends_buy_new(self) -> None:
        report = self.engine.evaluate(
            self.product(liquidity_score=85), self.listing(price=1500, shutter_count=20_000),
            self.market(), self.new_alternative(price=1595),
        )
        self.assertEqual(report.new_vs_used_recommendation, Recommendation.BUY_NEW)
        self.assertEqual(report.recommendation, Recommendation.BUY_NEW)

    def test_a7_iv_1200_versus_new_1595(self) -> None:
        report = self.engine.evaluate(
            self.product(liquidity_score=80),
            self.listing(price=1200, shutter_count=20_000, warranty_until="2027-04-30"),
            self.market(median_used_price=1400), self.new_alternative(price=1595),
        )
        self.assertEqual(report.new_vs_used_recommendation, Recommendation.BUY_USED)
        self.assertAlmostEqual(report.estimated_used_advantage, 395)

    def test_20_to_29_percent_discount_buy_new_rule(self) -> None:
        report = self.engine.evaluate(
            self.product(liquidity_score=80), self.listing(price=1200, shutter_count=20_000),
            self.market(), self.new_alternative(price=1595, warranty_months=24),
        )
        self.assertEqual(report.new_vs_used_recommendation, Recommendation.BUY_NEW)

    def test_20_to_29_percent_discount_buy_used_rule(self) -> None:
        report = self.engine.evaluate(
            self.product(liquidity_score=80), self.listing(price=1150, shutter_count=20_000),
            self.market(), self.new_alternative(price=1600),
        )
        self.assertEqual(report.new_vs_used_recommendation, Recommendation.BUY_USED)

    def test_20_to_29_percent_discount_falls_back_to_monitor(self) -> None:
        defects = [
            self.defect("mechanical_damage", "moderate", "Stiff focus ring"),
            self.defect("electronic_damage", "moderate", "Intermittent display"),
            self.defect("dust", "minor", "External dust"),
        ]
        report = self.engine.evaluate(
            self.product(category="Lens", liquidity_score=80),
            self.listing(price=1184, defects=defects),
            self.market(median_used_price=1200), self.new_alternative(price=1600),
        )
        self.assertEqual(report.new_vs_used_recommendation, Recommendation.MONITOR)

    def test_cracked_front_element_passes(self) -> None:
        report = self.engine.evaluate(
            self.product(category="Lens", liquidity_score=70),
            self.listing(price=300, defects=[self.defect("cracks", "critical", "Cracked front element")]),
            self.market(), self.new_alternative(),
        )
        self.assertEqual(report.recommendation, Recommendation.PASS)
        self.assertNotEqual(report.new_vs_used_recommendation, Recommendation.BUY_USED)

    def test_fungus_and_haze_require_manual_review(self) -> None:
        for category in ("fungus", "haze"):
            with self.subTest(category=category):
                report = self.engine.evaluate(
                    self.product(category="Lens", liquidity_score=70),
                    self.listing(defects=[self.defect(category, "moderate", category)]),
                    self.market(),
                )
                self.assertEqual(report.recommendation, Recommendation.MANUAL_REVIEW)

    def test_high_shutter_count_requires_manual_review(self) -> None:
        report = self.engine.evaluate(
            self.product(liquidity_score=70), self.listing(shutter_count=160_000), self.market()
        )
        self.assertEqual(report.recommendation, Recommendation.MANUAL_REVIEW)
        self.assertTrue(any(item.name == "shutter_count" and item.score_impact == -25 for item in report.factors))

    def test_warranty_invoice_and_accessories_are_explicit_factors(self) -> None:
        listing = self.listing(
            warranty_until="2027-04-30", invoice_available=True,
            accessories=["Sony original NP-FZ100 battery", "Sony original NP-FZ100 battery", "Sony VG-C4EM original grip"],
        )
        report = self.engine.evaluate(self.product(liquidity_score=80), listing, self.market())
        names = {item.name for item in report.factors}
        self.assertIn("active_warranty", names)
        self.assertIn("invoice", names)
        self.assertGreaterEqual(sum(item.score_impact for item in report.factors if item.category == "accessories"), 11)

    def test_unverified_filter_receives_no_bonus(self) -> None:
        report = self.engine.evaluate(
            self.product(category="Lens", liquidity_score=80),
            self.listing(accessories=["UV filter"]), self.market(),
        )
        accessory = next(item for item in report.factors if item.category == "accessories")
        self.assertEqual(accessory.score_impact, 0)
        self.assertIn("lacks identifiable", accessory.explanation)

    def test_identifiable_filter_receives_two_points(self) -> None:
        report = self.engine.evaluate(
            self.product(category="Lens", liquidity_score=80),
            self.listing(accessories=["NiSi True Color CPL 67mm filter"]), self.market(),
        )
        accessory = next(item for item in report.factors if item.category == "accessories")
        self.assertEqual(accessory.score_impact, 2)
        self.assertIn("NiSi True Color", accessory.evidence)

    def test_incomplete_listing_reduces_integer_confidence(self) -> None:
        report = self.engine.evaluate(
            self.product(),
            self.listing(condition="Unknown", shutter_count=None, warranty_until=None),
        )
        self.assertIsInstance(report.confidence, int)
        self.assertGreaterEqual(report.confidence, 10)
        self.assertLessEqual(report.confidence, 100)
        self.assertLess(report.confidence, 65)

    def test_missing_market_statistics_is_insufficient(self) -> None:
        report = self.engine.evaluate(self.product(liquidity_score=80), self.listing())
        self.assertEqual(report.recommendation, Recommendation.INSUFFICIENT_DATA)
        self.assertTrue(any(item.name == "missing_market_statistics" for item in report.factors))

    def test_falling_trend_increases_wait_probability(self) -> None:
        stable = self.engine.evaluate(self.product(liquidity_score=80), self.listing(), self.market(price_trend_percent=0))
        falling = self.engine.evaluate(self.product(liquidity_score=80), self.listing(), self.market(price_trend_percent=-8))
        self.assertGreater(falling.wait_probability, stable.wait_probability)

    def test_every_score_change_has_a_factor(self) -> None:
        report = self.engine.evaluate(
            self.product(liquidity_score=80),
            self.listing(price=1000, shutter_count=5_000, invoice_available=True, original_box_available=True),
            self.market(median_used_price=1400),
        )
        self.assertEqual(report.buy_score, max(0, min(100, 50 + sum(item.score_impact for item in report.factors))))

    def test_mismatched_currency_disables_new_comparison(self) -> None:
        report = self.engine.evaluate(
            self.product(liquidity_score=80), self.listing(currency="EUR"),
            self.market(currency="EUR"), self.new_alternative(currency="USD"),
        )
        self.assertEqual(report.new_vs_used_recommendation, Recommendation.INSUFFICIENT_DATA)
        self.assertIsNone(report.estimated_used_advantage)
        self.assertTrue(any("currencies" in warning for warning in report.warnings))

    def test_missing_currency_disables_new_comparison(self) -> None:
        report = self.engine.evaluate(
            self.product(liquidity_score=80), self.listing(currency=""),
            self.market(currency=None), self.new_alternative(currency="EUR"),
        )
        self.assertEqual(report.new_vs_used_recommendation, Recommendation.INSUFFICIENT_DATA)
        self.assertIsNone(report.estimated_used_advantage)

    def test_invalid_defect_confidence_triggers_manual_review(self) -> None:
        report = self.engine.evaluate(
            self.product(category="Lens", liquidity_score=80),
            self.listing(defects=[self.defect("scratches", "minor", "Scratch", confidence=1.5)]),
            self.market(),
        )
        self.assertEqual(report.recommendation, Recommendation.MANUAL_REVIEW)
        self.assertLessEqual(report.confidence, 35)

    def test_invalid_defect_category_or_severity_triggers_manual_review(self) -> None:
        for defect in (
            self.defect("not_a_category", "minor", "Unknown issue"),
            self.defect("scratches", "extreme", "Unknown severity"),
        ):
            with self.subTest(defect=defect):
                report = self.engine.evaluate(
                    self.product(category="Lens", liquidity_score=80), self.listing(defects=[defect]), self.market()
                )
                self.assertEqual(report.recommendation, Recommendation.MANUAL_REVIEW)
                self.assertTrue(any("invalid structured data" in warning for warning in report.warnings))

    def test_expected_fair_price_is_unadjusted(self) -> None:
        report = self.engine.evaluate(
            self.product(category="Lens", price_used=900, liquidity_score=80),
            self.listing(price=300, defects=[self.defect("cracks", "critical", "Crack")], accessories=["NiSi CPL 67mm filter"]),
            self.market(median_used_price=1000),
        )
        self.assertEqual(report.expected_fair_price, 1000)
        fallback = self.engine.evaluate(
            self.product(price_used=900, liquidity_score=80), self.listing(), None
        )
        self.assertEqual(fallback.expected_fair_price, 900)

    def test_decision_sources_parse_as_python_3_9(self) -> None:
        for source_path in (PROJECT_ROOT / "src" / "decision").glob("*.py"):
            with self.subTest(source=source_path.name):
                ast.parse(source_path.read_text(), feature_version=(3, 9))

    @staticmethod
    def product(
        category: str = "Camera", price_used: Optional[float] = None,
        liquidity_score: Optional[float] = None,
    ) -> Product:
        return Product(
            "sony-alpha-a7-iv", category, "Mirrorless" if category == "Camera" else "Prime",
            "Sony", "Alpha A7", "IV", "sony-e", 2021, None, price_used,
            None, None, liquidity_score, None, None, "",
        )

    @staticmethod
    def listing(**overrides) -> Listing:
        values = dict(
            external_id="listing-1", source="Test", title="Test listing",
            url="https://example.invalid/1", price=1200.0, currency="EUR",
            condition="Used - Excellent", location="Rome", seller="Seller",
            description="Clean and functional", detected_at=datetime.now(timezone.utc),
            raw_data={}, connector_name="test", shutter_count=20_000,
            warranty_until=None, invoice_available=None, original_box_available=None,
            accessories=[], defects=[], seller_claims=[], missing_information=[],
        )
        values.update(overrides)
        return Listing(**values)

    @staticmethod
    def market(**overrides) -> MarketStatistics:
        values = dict(
            median_used_price=1400.0, lowest_recent_used_price=1100.0,
            median_new_price=1595.0, sample_size=20, price_trend_percent=0.0,
            observation_window_days=90, currency="EUR",
        )
        values.update(overrides)
        return MarketStatistics(**values)

    @staticmethod
    def new_alternative(**overrides) -> NewAlternative:
        values = dict(
            price=1600.0, currency="EUR", warranty_months=24,
            return_window_days=30, seller_reliability_score=95.0, notes="Retail",
        )
        values.update(overrides)
        return NewAlternative(**values)

    @staticmethod
    def defect(category: str, severity: str, description: str, confidence: float = 1.0) -> ListingDefect:
        return ListingDefect(category, description, severity, "item", description, confidence)


if __name__ == "__main__":
    unittest.main()
