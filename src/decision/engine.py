"""Orchestration for the explainable Decision Engine V1."""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Tuple

from catalog import Product
from connectors.models import DEFECT_CATEGORIES, DEFECT_SEVERITIES, Listing

from .explanations import key_reasons
from .models import (
    DecisionFactor, DecisionReport, MarketStatistics, NewAlternative,
    Recommendation,
)
from .rules import (
    OPTICAL_RISK_CATEGORIES, evaluate_accessories, evaluate_condition,
    evaluate_defects, evaluate_documentation, evaluate_market_price,
    evaluate_shutter_count, evaluate_warranty, factor, resale_score,
    wait_probability,
)


class DecisionEngine:
    def __init__(self, as_of: Optional[date] = None) -> None:
        self.as_of = as_of or date.today()

    def evaluate(
        self,
        product: Product,
        listing: Listing,
        market: Optional[MarketStatistics] = None,
        new_alternative: Optional[NewAlternative] = None,
    ) -> DecisionReport:
        factors: List[DecisionFactor] = []
        warnings: List[str] = []
        missing: List[str] = list(listing.missing_information)

        market_valid = self._market_valid(listing, market)
        usable_market = market if market_valid else None
        if market and not market_valid:
            warnings.append("Market statistics currency is missing or differs from the listing currency.")

        factors.extend(evaluate_market_price(listing, usable_market))
        condition_factors, condition_missing = evaluate_condition(listing)
        factors.extend(condition_factors)
        missing = self._merge(missing, condition_missing)

        defect_factors, defect_warnings, manual_review, must_pass, major_or_critical = evaluate_defects(listing)
        factors.extend(defect_factors)
        warnings.extend(defect_warnings)
        factors.extend(evaluate_shutter_count(product, listing))

        warranty_factors, active_warranty, warranty_unknown = evaluate_warranty(listing, self.as_of)
        factors.extend(warranty_factors)
        if warranty_unknown:
            missing = self._merge(missing, ["warranty status"])
            warnings.append("Warranty status is missing or unparseable.")
        factors.extend(evaluate_documentation(listing))
        accessory_factors, accessory_bonus = evaluate_accessories(product, listing.accessories)
        factors.extend(accessory_factors)

        buy_score = max(0, min(100, 50 + sum(item.score_impact for item in factors)))
        risk_score = max(0, min(100, sum(
            abs(item.score_impact) for item in factors
            if item.score_impact < 0 and item.category in {"condition", "defect"}
        )))
        confidence, confidence_factors, confidence_warnings = self._confidence(
            product, listing, usable_market, warranty_unknown
        )
        factors.extend(confidence_factors)
        warnings.extend(confidence_warnings)
        if new_alternative and (
            not listing.currency
            or not new_alternative.currency
            or listing.currency.casefold() != new_alternative.currency.casefold()
        ):
            confidence = max(10, confidence - 15)
            factors.append(factor(
                "new_comparison_currency_confidence", "confidence", 0,
                f"used_currency={listing.currency!r}; new_currency={new_alternative.currency!r}",
                "Confidence reduced by 15 points because the new-versus-used currencies cannot be compared.", 100,
            ))

        invalid_defect = any(
            defect.category not in DEFECT_CATEGORIES
            or defect.severity not in DEFECT_SEVERITIES
            or not defect.description.strip()
            or not 0 <= defect.confidence <= 1
            for defect in listing.defects
        )
        contradictory = invalid_defect
        if contradictory:
            confidence = min(confidence, 35)
            manual_review = True

        new_recommendation, advantage, new_factor, new_warnings = self._compare_new(
            product, listing, new_alternative, active_warranty, accessory_bonus,
            risk_score, confidence, major_or_critical, contradictory, buy_score,
        )
        factors.append(new_factor)
        warnings.extend(new_warnings)

        recommendation = self._final_recommendation(
            listing, usable_market, new_alternative, new_recommendation,
            buy_score, manual_review, must_pass,
        )
        if product.category.casefold() == "camera" and listing.shutter_count is not None and listing.shutter_count >= 150_000:
            recommendation = Recommendation.MANUAL_REVIEW
            warnings.append("Shutter count at or above 150,000 requires manual review.")

        fair_price = (
            usable_market.median_used_price
            if usable_market and usable_market.median_used_price is not None and usable_market.median_used_price > 0
            else product.price_used
        )
        ownership_factors = {"price", "protection", "documentation", "accessories"}
        ownership_cost = None
        if usable_market or new_alternative:
            ownership_cost = max(0, min(100, 50 + sum(
                item.score_impact for item in factors if item.category in ownership_factors
            )))

        return DecisionReport(
            buy_score=buy_score,
            confidence=confidence,
            recommendation=recommendation,
            expected_fair_price=fair_price,
            ownership_cost_score=ownership_cost,
            resale_score=resale_score(product),
            risk_score=risk_score,
            wait_probability=wait_probability(listing, usable_market),
            new_vs_used_recommendation=new_recommendation,
            estimated_used_advantage=advantage,
            factors=factors,
            reasons=key_reasons(factors),
            warnings=self._unique(warnings),
            missing_information=self._unique(missing),
        )

    def _confidence(
        self, product: Product, listing: Listing,
        market: Optional[MarketStatistics], warranty_unknown: bool,
    ) -> Tuple[int, List[DecisionFactor], List[str]]:
        confidence = 100
        factors: List[DecisionFactor] = []
        warnings: List[str] = []

        def deduct(name: str, amount: int, evidence: str) -> None:
            nonlocal confidence
            confidence -= amount
            factors.append(factor(name, "confidence", 0, evidence, f"Confidence reduced by {amount} points: {evidence}.", 100))

        if market is None:
            deduct("missing_market_statistics", 25, "valid market statistics unavailable")
        elif market.sample_size < 5:
            deduct("small_market_sample", 10, f"market sample size={market.sample_size}")
        if not listing.condition.strip() or listing.condition.casefold() in {"unknown", "not specified"}:
            deduct("missing_condition_confidence", 15, "condition details missing")
        if warranty_unknown:
            deduct("missing_warranty_confidence", 10, "warranty status missing or unparseable")
        if product.category.casefold() == "camera" and listing.shutter_count is None:
            deduct("missing_shutter_confidence", 10, "camera shutter count missing")
        if any(defect.severity == "unknown" for defect in listing.defects):
            deduct("unknown_defect_severity", 15, "relevant defect severity unknown")
        if product.liquidity_score is None:
            deduct("missing_liquidity_confidence", 10, "product liquidity unavailable")
        if listing.price is None:
            deduct("missing_price_confidence", 30, "listing price missing")
        return max(10, min(100, confidence)), factors, warnings

    def _compare_new(
        self, product: Product, listing: Listing,
        alternative: Optional[NewAlternative], active_warranty: bool,
        accessory_bonus: int, risk_score: int, confidence: int,
        major_or_critical: bool, contradictory: bool, buy_score: int,
    ) -> Tuple[Recommendation, Optional[float], DecisionFactor, List[str]]:
        warnings: List[str] = []
        if alternative is None:
            return Recommendation.INSUFFICIENT_DATA, None, factor(
                "new_vs_used_unavailable", "new_vs_used", 0, "new alternative unavailable",
                "A new-versus-used recommendation requires a new alternative.", 50,
            ), warnings
        if not listing.currency or not alternative.currency or listing.currency.casefold() != alternative.currency.casefold():
            warnings.append("New-versus-used comparison skipped because currencies are missing or do not match.")
            return Recommendation.INSUFFICIENT_DATA, None, factor(
                "new_vs_used_currency", "new_vs_used", 0,
                f"used_currency={listing.currency!r}; new_currency={alternative.currency!r}",
                "No currency conversion is performed in V1.", 20,
            ), warnings
        if listing.price is None or alternative.price <= 0:
            return Recommendation.INSUFFICIENT_DATA, None, factor(
                "new_vs_used_price_missing", "new_vs_used", 0, "valid prices unavailable",
                "The comparison requires valid used and new prices.", 20,
            ), warnings

        advantage = alternative.price - listing.price
        discount = advantage / alternative.price * 100
        no_defects = not listing.defects
        shutter = listing.shutter_count
        if discount < 10:
            exceptional = accessory_bonus >= 8 and active_warranty and no_defects and confidence >= 75
            recommendation = Recommendation.BUY_USED if exceptional else Recommendation.BUY_NEW
        elif discount < 20:
            meaningful_wear = bool(listing.defects) or (shutter is not None and shutter >= 40_000)
            recommendation = Recommendation.BUY_NEW if not active_warranty or meaningful_wear else self._score_recommendation(buy_score)
        elif discount < 30:
            buy_new = (
                major_or_critical or risk_score >= 40
                or (shutter is not None and shutter >= 80_000)
                or (not active_warranty and alternative.warranty_months >= 12 and discount < 25)
                or contradictory
            )
            buy_used = (
                not major_or_critical and risk_score < 25
                and (shutter is None or shutter < 80_000)
                and confidence >= 65
                and (active_warranty or accessory_bonus >= 5 or discount >= 25)
            )
            if buy_new:
                recommendation = Recommendation.BUY_NEW
            elif buy_used:
                recommendation = Recommendation.BUY_USED
            else:
                recommendation = Recommendation.NEGOTIATE if buy_score >= 60 else Recommendation.MONITOR
        else:
            recommendation = Recommendation.BUY_USED if not major_or_critical and not contradictory else Recommendation.MANUAL_REVIEW
        return recommendation, advantage, factor(
            "new_vs_used_comparison", "new_vs_used", 0,
            f"used={listing.price:.2f} {listing.currency}; new={alternative.price:.2f} {alternative.currency}; discount={discount:.2f}%",
            f"The explicit new-versus-used rules recommend {recommendation.value}.", 100,
        ), warnings

    @staticmethod
    def _final_recommendation(
        listing: Listing, market: Optional[MarketStatistics],
        alternative: Optional[NewAlternative], new_recommendation: Recommendation,
        buy_score: int, manual_review: bool, must_pass: bool,
    ) -> Recommendation:
        if listing.price is None:
            return Recommendation.INSUFFICIENT_DATA
        if must_pass:
            return Recommendation.PASS
        if manual_review:
            return Recommendation.MANUAL_REVIEW
        if new_recommendation == Recommendation.BUY_NEW:
            return Recommendation.BUY_NEW
        if new_recommendation == Recommendation.BUY_USED:
            return Recommendation.BUY_USED
        if market is None and alternative is None:
            return Recommendation.INSUFFICIENT_DATA
        return DecisionEngine._score_recommendation(buy_score)

    @staticmethod
    def _score_recommendation(score: int) -> Recommendation:
        if score >= 75:
            return Recommendation.BUY_USED
        if score >= 60:
            return Recommendation.NEGOTIATE
        if score >= 45:
            return Recommendation.MONITOR
        return Recommendation.PASS

    @staticmethod
    def _market_valid(listing: Listing, market: Optional[MarketStatistics]) -> bool:
        return bool(
            market and listing.currency and market.currency
            and listing.currency.casefold() == market.currency.casefold()
        )

    @staticmethod
    def _merge(left: List[str], right: List[str]) -> List[str]:
        return DecisionEngine._unique(left + right)

    @staticmethod
    def _unique(values: List[str]) -> List[str]:
        return list(dict.fromkeys(value for value in values if value))
