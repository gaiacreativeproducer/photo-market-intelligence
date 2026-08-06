"""Tests for deterministic Ownership Engine V1."""

from __future__ import annotations

import ast
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from catalog import Product
from connectors.models import ListingDefect
from market.models import MarketSnapshot
from ownership import (
    OwnershipEngine, OwnershipHorizon, OwnershipRecommendation,
    PurchaseOption, PurchaseType,
)


class OwnershipEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.camera = self.product("sony-alpha-a7-iv", "Camera", liquidity=80)
        self.lens = self.product("sigma-lens", "Lens", liquidity=70)
        self.horizon = OwnershipHorizon(12, "MEDIUM", True)
        self.used_market = self.snapshot(
            self.camera.id, "USED", 1400, depreciation_12=10,
            depreciation_24=20,
        )
        self.new_market = self.snapshot(self.camera.id, "NEW", 1595)

    def test_a7_iv_used_1200_versus_new_1595(self) -> None:
        comparison = self.engine().compare(
            self.camera,
            [self.new_option(), self.used_option()],
            self.horizon,
        )
        self.assertEqual(comparison.recommendation, OwnershipRecommendation.PREFER_NEW)
        self.assertEqual(comparison.recommended_option_id, "new")
        self.assertIsNotNone(comparison.break_even_target_price)
        self.assertIsNotNone(comparison.break_even_discount_percent)

    def test_small_discount_prefers_new(self) -> None:
        comparison = self.engine().compare(
            self.camera,
            [self.new_option(), self.used_option(price=1500, shutter=60_000)],
            self.horizon,
        )
        self.assertEqual(comparison.recommendation, OwnershipRecommendation.PREFER_NEW)

    def test_large_clean_used_discount_prefers_used(self) -> None:
        used = self.used_option(price=700, shutter=5_000, warranty=12, transferable=True)
        comparison = self.engine().compare(
            self.camera, [self.new_option(), used], self.horizon
        )
        self.assertEqual(comparison.recommendation, OwnershipRecommendation.PREFER_USED)

    def test_equivalent_ownership_cost(self) -> None:
        product = self.lens
        new_market = self.snapshot(product.id, "NEW", 1000)
        used_market = self.snapshot(product.id, "USED", 1000, depreciation_12=0)
        new = self.option(
            "new", PurchaseType.NEW, 1000, new_market,
            warranty=0, returns=0,
        )
        used = self.option(
            "used", PurchaseType.USED, 1000, used_market,
            warranty=0, returns=0,
        )
        comparison = self.engine().compare(product, [new, used], self.horizon)
        self.assertEqual(comparison.recommendation, OwnershipRecommendation.EQUIVALENT)

    def test_invoice_is_explanatory_not_monetary(self) -> None:
        known = self.engine().project(
            self.camera, self.used_option(invoice=True), self.horizon
        )
        unknown = self.engine().project(
            self.camera, self.used_option(invoice=None), self.horizon
        )
        self.assertEqual(known.protected_value, unknown.protected_value)
        self.assertEqual(known.confidence, unknown.confidence + 5)
        invoice_factor = next(item for item in known.factors if item.name == "invoice_provenance")
        self.assertEqual(invoice_factor.impact, 0)

    def test_new_condition_has_no_monetary_protection(self) -> None:
        option = replace(
            self.new_option(), warranty_months=0, return_window_days=0,
            accessories=[], invoice_available=False,
        )
        projection = self.engine().project(
            self.camera, option, self.horizon, [option, self.used_option()]
        )
        self.assertEqual(projection.protected_value, 0)
        condition = next(item for item in projection.factors if item.name == "condition_provenance")
        self.assertEqual(condition.impact, 0)

    def test_no_warranty_or_return_is_not_risk_cost(self) -> None:
        option = self.used_option(warranty=0, returns=0, shutter=0, reliability=100)
        projection = self.engine().project(self.camera, option, self.horizon)
        risk_names = {item.name for item in projection.factors if item.category == "risk_cost"}
        self.assertNotIn("warranty", " ".join(risk_names))
        self.assertNotIn("return", " ".join(risk_names))
        self.assertEqual(projection.risk_cost, 0)

    def test_unknown_warranty_reduces_confidence(self) -> None:
        known = self.engine().project(
            self.camera, self.used_option(warranty=0), self.horizon
        )
        unknown = self.engine().project(
            self.camera, self.used_option(warranty=None), self.horizon
        )
        self.assertEqual(known.confidence, unknown.confidence + 10)

    def test_nontransferable_used_warranty_has_no_value(self) -> None:
        option = self.used_option(warranty=12, transferable=False)
        projection = self.engine().project(self.camera, option, self.horizon)
        warranty = next(item for item in projection.factors if item.name == "warranty_protection")
        self.assertEqual(warranty.impact, 0)
        self.assertTrue(any("transferability" in warning for warning in projection.warnings))

    def test_warranty_and_return_protected_value(self) -> None:
        option = replace(
            self.new_option(), purchase_price=1000, estimated_landed_cost=1000,
            warranty_months=24, return_window_days=30,
        )
        projection = self.engine().project(
            self.camera, option, self.horizon,
            [option, self.used_option(price=800)],
        )
        self.assertEqual(projection.protected_value, 100)
        names = {item.name for item in projection.factors}
        self.assertIn("warranty_protection", names)
        self.assertIn("return_window_protection", names)

    def test_minor_cosmetic_damage_has_zero_risk(self) -> None:
        defect = self.defect("cosmetic_damage", "minor")
        projection = self.engine().project(
            self.camera,
            replace(self.used_option(shutter=0, reliability=100), defects=[defect]),
            self.horizon,
        )
        defect_factor = next(item for item in projection.factors if item.name == "defect_ownership_risk")
        self.assertEqual(defect_factor.impact, 0)

    def test_critical_cosmetic_is_eight_percent_not_forty(self) -> None:
        defect = self.defect("cosmetic_damage", "critical", "body", "Severe paint loss")
        projection = self.engine().project(
            self.camera, replace(self.used_option(), defects=[defect]), self.horizon
        )
        factor = next(item for item in projection.factors if item.name == "defect_ownership_risk")
        self.assertEqual(factor.value, 8)
        self.assertFalse(projection.manual_review)

    def test_defect_risk_and_resale_are_separate(self) -> None:
        defect = self.defect("electronic_damage", "major")
        projection = self.engine().project(
            self.camera, replace(self.used_option(), defects=[defect]), self.horizon
        )
        risk = next(item for item in projection.factors if item.name == "defect_ownership_risk")
        resale = next(item for item in projection.factors if item.name == "defect_resale_effect")
        self.assertGreater(risk.impact, 0)
        self.assertLess(resale.impact, 0)
        self.assertIn("ownership or repair", risk.explanation)
        self.assertIn("future resale", resale.explanation)

    def test_critical_crack_prevents_used_recommendation(self) -> None:
        product = self.lens
        new_market = self.snapshot(product.id, "NEW", 1200)
        used_market = self.snapshot(product.id, "USED", 900, depreciation_12=10)
        new = self.option("new", PurchaseType.NEW, 1200, new_market)
        used = replace(
            self.option("used", PurchaseType.USED, 300, used_market),
            defects=[self.defect("cracks", "critical", "front element")],
        )
        comparison = self.engine().compare(product, [new, used], self.horizon)
        self.assertEqual(comparison.recommendation, OwnershipRecommendation.MANUAL_REVIEW)

    def test_high_shutter_count_risk_and_review(self) -> None:
        projection = self.engine().project(
            self.camera, self.used_option(shutter=150_000), self.horizon
        )
        factor = next(item for item in projection.factors if item.name == "shutter_ownership_risk")
        self.assertEqual(factor.value, 15)
        self.assertTrue(projection.manual_review)

    def test_planned_resale_selects_applicable_cost(self) -> None:
        option = self.used_option()
        with_resale = self.engine().project(
            self.camera, option, OwnershipHorizon(12, "MEDIUM", True)
        )
        without_resale = self.engine().project(
            self.camera, option, OwnershipHorizon(12, "MEDIUM", False)
        )
        self.assertEqual(
            with_resale.estimated_net_ownership_cost,
            with_resale.estimated_net_ownership_cost_with_resale,
        )
        self.assertEqual(
            without_resale.estimated_net_ownership_cost,
            without_resale.estimated_net_ownership_cost_without_resale,
        )
        self.assertNotEqual(
            without_resale.estimated_net_ownership_cost,
            without_resale.estimated_net_ownership_cost_with_resale,
        )

    def test_unplanned_resale_effect_is_informational(self) -> None:
        defect = self.defect("electronic_damage", "major")
        projection = self.engine().project(
            self.camera, replace(self.used_option(), defects=[defect]),
            OwnershipHorizon(12, "MEDIUM", False),
        )
        resale = next(item for item in projection.factors if item.name == "defect_resale_effect")
        self.assertEqual(resale.impact, 0)

    def test_duplicate_defects_count_once(self) -> None:
        defect = self.defect("electronic_damage", "moderate")
        projection = self.engine().project(
            self.camera, replace(self.used_option(), defects=[defect, defect]), self.horizon
        )
        factors = [item for item in projection.factors if item.name == "defect_ownership_risk"]
        resale = [item for item in projection.factors if item.name == "defect_resale_effect"]
        self.assertEqual(len(factors), 1)
        self.assertEqual(len(resale), 0)

    def test_accessories_with_references_and_two_battery_limit(self) -> None:
        option = replace(
            self.used_option(),
            accessories=["Sony original battery"] * 3 + ["Unknown strap"],
        )
        projection = self.engine({"sony original battery": 50}).project(
            self.camera, option, self.horizon
        )
        self.assertEqual(projection.protected_value, 100)
        matched = [item for item in projection.factors if item.name == "referenced_accessory"]
        self.assertEqual(len(matched), 2)
        self.assertTrue(all("matched_reference" in item.evidence for item in matched))
        self.assertLess(projection.confidence, 100)

    def test_accessory_value_cap(self) -> None:
        option = replace(self.used_option(price=1000), accessories=["DJI RS 4"])
        projection = self.engine({"dji rs 4": 500}).project(
            self.camera, option, self.horizon
        )
        self.assertEqual(projection.protected_value, 150)
        self.assertTrue(any(item.name == "accessory_value_cap" for item in projection.factors))

    def test_12_and_24_month_used_depreciation(self) -> None:
        option = self.used_option()
        year = self.engine().project(
            self.camera, option, OwnershipHorizon(12, "MEDIUM", True)
        )
        two_year = self.engine().project(
            self.camera, option, OwnershipHorizon(24, "MEDIUM", True)
        )
        self.assertEqual(year.estimated_depreciation_percent, 10)
        self.assertEqual(two_year.estimated_depreciation_percent, 20)

    def test_new_to_used_first_year_drop(self) -> None:
        new = self.new_option()
        projection = self.engine().project(
            self.camera, new, self.horizon, [new, self.used_option()]
        )
        expected = (1 - 1400 / 1595) * 100
        self.assertAlmostEqual(projection.estimated_depreciation_percent, expected)

    def test_invalid_depreciation_above_100_is_ignored(self) -> None:
        market = replace(self.used_market, estimated_12_month_depreciation=101)
        projection = self.engine().project(
            self.camera, replace(self.used_option(), market_snapshot=market), self.horizon
        )
        self.assertIsNone(projection.estimated_depreciation_percent)
        self.assertTrue(any("above 100" in warning for warning in projection.warnings))

    def test_negative_depreciation_represents_appreciation(self) -> None:
        market = replace(self.used_market, estimated_12_month_depreciation=-10)
        projection = self.engine().project(
            self.camera, replace(self.used_option(), market_snapshot=market), self.horizon
        )
        self.assertEqual(projection.estimated_depreciation_percent, -10)
        self.assertGreater(projection.estimated_resale_value, projection.acquisition_cost)

    def test_break_even_numeric_search_is_explainable(self) -> None:
        comparison = self.engine().compare(
            self.camera, [self.new_option(), self.used_option()], self.horizon
        )
        self.assertIsNotNone(comparison.break_even_target_price)
        self.assertIsNotNone(comparison.break_even_discount_percent)
        names = {item.name for item in comparison.factors}
        self.assertEqual(names, {"break_even_target", "break_even_discount"})
        self.assertTrue(any("bounded" in item.evidence for item in comparison.factors))

    def test_near_break_even_produces_negotiation_target(self) -> None:
        base = self.engine().compare(
            self.camera, [self.new_option(), self.used_option(price=1)], self.horizon
        )
        target = base.break_even_target_price
        self.assertIsNotNone(target)
        current = target * 1.05
        comparison = self.engine().compare(
            self.camera,
            [self.new_option(), self.used_option(price=current)],
            self.horizon,
        )
        self.assertEqual(comparison.recommendation, OwnershipRecommendation.NEGOTIATE_USED)
        self.assertEqual(comparison.break_even_target_price, target)

    def test_break_even_unavailable_without_depreciation(self) -> None:
        used = replace(
            self.used_option(),
            market_snapshot=replace(
                self.used_market, estimated_12_month_depreciation=None
            ),
        )
        comparison = self.engine().compare(
            self.camera, [self.new_option(), used],
            OwnershipHorizon(12, "MEDIUM", False),
        )
        self.assertIsNone(comparison.break_even_target_price)
        self.assertIsNone(comparison.break_even_discount_percent)

    def test_mismatched_currency_is_insufficient(self) -> None:
        used = replace(self.used_option(), currency="USD")
        comparison = self.engine().compare(
            self.camera, [self.new_option(), used], self.horizon
        )
        self.assertEqual(comparison.recommendation, OwnershipRecommendation.INSUFFICIENT_DATA)

    def test_foreign_option_without_landed_cost_is_insufficient(self) -> None:
        new = replace(
            self.new_option(), source_country="Germany",
            estimated_landed_cost=None,
        )
        comparison = self.engine().compare(
            self.camera, [new, self.used_option()], self.horizon
        )
        self.assertEqual(comparison.recommendation, OwnershipRecommendation.INSUFFICIENT_DATA)

    def test_low_confidence_is_insufficient_not_prefer_new(self) -> None:
        used = replace(
            self.used_option(), warranty_months=None,
            return_window_days=None, condition_known=None,
            shutter_count=None, seller_reliability_score=None,
            invoice_available=None,
        )
        comparison = self.engine().compare(
            self.camera, [self.new_option(), used], self.horizon
        )
        self.assertEqual(comparison.recommendation, OwnershipRecommendation.INSUFFICIENT_DATA)

    def test_confidence_does_not_depend_on_price_or_recommendation(self) -> None:
        cheap = self.engine().project(
            self.camera, self.used_option(price=500), self.horizon
        )
        expensive = self.engine().project(
            self.camera, self.used_option(price=1400), self.horizon
        )
        self.assertEqual(cheap.confidence, expensive.confidence)

    def test_every_economic_adjustment_has_a_factor(self) -> None:
        projection = self.engine({"sony original battery": 50}).project(
            self.camera,
            replace(
                self.used_option(), accessories=["Sony original battery"],
                defects=[self.defect("electronic_damage", "moderate")],
            ),
            self.horizon,
        )
        self.assertAlmostEqual(
            projection.protected_value,
            sum(item.impact for item in projection.factors if item.category == "protected_value"),
        )
        self.assertAlmostEqual(
            projection.risk_cost,
            sum(item.impact for item in projection.factors if item.category == "risk_cost"),
        )

    def test_sources_parse_as_python_3_9(self) -> None:
        for source_path in (PROJECT_ROOT / "src" / "ownership").glob("*.py"):
            with self.subTest(source=source_path.name):
                ast.parse(source_path.read_text(), feature_version=(3, 9))

    def engine(self, references=None) -> OwnershipEngine:
        return OwnershipEngine(references or {})

    def new_option(self) -> PurchaseOption:
        return self.option(
            "new", PurchaseType.NEW, 1595, self.new_market,
            warranty=24, returns=14, shutter=0,
        )

    def used_option(
        self, price=1200, shutter=60_000, warranty=0, returns=0,
        transferable=False, reliability=95, invoice=True,
    ) -> PurchaseOption:
        return self.option(
            "used", PurchaseType.USED, price, self.used_market,
            warranty=warranty, returns=returns, shutter=shutter,
            transferable=transferable, reliability=reliability,
            invoice=invoice,
        )

    def option(
        self, option_id, purchase_type, price, snapshot,
        warranty=0, returns=14, shutter=None, transferable=None,
        reliability=95, invoice=True,
    ) -> PurchaseOption:
        return PurchaseOption(
            option_id, purchase_type, price, "EUR", warranty, returns,
            price, shutter, [], [], reliability, snapshot, "",
            "Italy", "Italy", transferable, invoice, True, False, [],
        )

    @staticmethod
    def defect(category, severity, component="body", description="Visible defect"):
        return ListingDefect(
            category, description, severity, component, description, 1.0
        )

    @staticmethod
    def product(product_id, category, liquidity=None):
        return Product(
            product_id, category, "Test", "Test", "Model", "", "none",
            None, None, None, None, None, liquidity, None, None, "",
        )

    @staticmethod
    def snapshot(
        product_id, segment, median, depreciation_12=None,
        depreciation_24=None, confidence=90, trend_30=None,
    ):
        return MarketSnapshot(
            product_id, "Italy", ["Italy"], "EUR", segment,
            datetime(2026, 8, 1, tzinfo=timezone.utc), 10, 10, 0,
            median, median, median, median, median, 0, median, median,
            median, median, 0, confidence, trend_30, None, None,
            depreciation_12, depreciation_24, 95, [], [],
        )


if __name__ == "__main__":
    unittest.main()
