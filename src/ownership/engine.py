"""Deterministic new-versus-used ownership comparison orchestration."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from catalog import Product
from market.models import MarketSnapshot

from .models import (
    OwnershipComparison, OwnershipFactor, OwnershipHorizon,
    OwnershipProjection, OwnershipRecommendation, PurchaseOption, PurchaseType,
)
from .rules import (
    acquisition_cost, factor, protection_factors, risk_factors, unique_defects,
)


class OwnershipEngine:
    def __init__(
        self, accessory_reference_prices: Optional[Mapping[str, float]] = None
    ) -> None:
        self.accessory_reference_prices = dict(accessory_reference_prices or {})

    def project(
        self, product: Product, option: PurchaseOption,
        horizon: OwnershipHorizon,
        comparison_options: Sequence[PurchaseOption] = (),
    ) -> OwnershipProjection:
        factors: List[OwnershipFactor] = []
        warnings: List[str] = []
        missing: List[str] = list(option.missing_information)
        cost = acquisition_cost(option)
        if cost is None:
            missing.append("comparable acquisition cost")
            factors.append(factor(
                "acquisition_cost_unavailable", "acquisition", 0, 0,
                "landed cost unavailable or purchase is not confirmed domestic",
                "Ownership cost cannot be calculated without comparable acquisition cost.", 20,
            ))
            protected_value = 0.0
            risk_cost = 0.0
            protection = []
            risk = []
            unknown_accessories = len(option.accessories)
            manual_review = option.contradictory
            major_risk = False
        else:
            factors.append(factor(
                "acquisition_cost", "acquisition", cost, cost,
                "landed cost" if option.estimated_landed_cost is not None else "confirmed domestic purchase price",
                "Acquisition cost uses landed cost when available, otherwise confirmed domestic price.",
            ))
            protection, protected_value, unknown_accessories, protection_warnings = protection_factors(
                option, cost, self.accessory_reference_prices
            )
            risk, risk_cost, manual_review, major_risk = risk_factors(
                product, option, cost
            )
            warnings.extend(protection_warnings)
            factors.extend(protection)
            factors.extend(risk)

        depreciation, depreciation_factors, depreciation_warnings = self._depreciation(
            product, option, horizon, comparison_options
        )
        factors.extend(depreciation_factors)
        warnings.extend(depreciation_warnings)
        resale_value, resale_factors = self._resale_value(
            product, option, horizon, cost, depreciation
        )
        factors.extend(resale_factors)

        without_resale = (
            cost + risk_cost - protected_value if cost is not None else None
        )
        with_resale = (
            without_resale - resale_value
            if without_resale is not None and resale_value is not None
            else None
        )
        applicable = with_resale if horizon.planned_resale else without_resale
        if not horizon.planned_resale and resale_value is not None:
            warnings.append(
                "Resale value is informational because planned_resale is False and is not subtracted from the applicable ownership cost."
            )
        confidence, confidence_factors = self._confidence(
            product, option, cost, depreciation, unknown_accessories
        )
        factors.extend(confidence_factors)
        return OwnershipProjection(
            option.option_id, cost, protected_value, risk_cost, depreciation,
            resale_value, applicable, with_resale, without_resale,
            product.liquidity_score, confidence, factors,
            self._unique(warnings), self._unique(missing), manual_review,
            major_risk,
        )

    def compare(
        self, product: Product, options: List[PurchaseOption],
        horizon: OwnershipHorizon,
    ) -> OwnershipComparison:
        by_type = {option.purchase_type: option for option in options}
        new_option = by_type.get(PurchaseType.NEW)
        used_option = by_type.get(PurchaseType.USED)
        if new_option is None or used_option is None:
            projections = [
                self.project(product, option, horizon, options) for option in options
            ]
            return OwnershipComparison(
                None, OwnershipRecommendation.INSUFFICIENT_DATA,
                min((item.confidence for item in projections), default=0),
                projections, None, None, None, None, [],
                ["A direct comparison requires one NEW and one USED option."], [],
            )

        new_projection = self.project(product, new_option, horizon, options)
        used_projection = self.project(product, used_option, horizon, options)
        projections = [new_projection, used_projection]
        confidence = min(item.confidence for item in projections)
        warnings = self._unique(new_projection.warnings + used_projection.warnings)
        factors: List[OwnershipFactor] = []
        currencies_match = bool(
            new_option.currency and used_option.currency
            and new_option.currency.casefold() == used_option.currency.casefold()
        )
        comparable = (
            currencies_match
            and new_projection.acquisition_cost is not None
            and used_projection.acquisition_cost is not None
        )
        if not currencies_match:
            warnings.append("Ownership options use different or missing currencies; no conversion is performed.")
        new_cost = new_projection.estimated_net_ownership_cost
        used_cost = used_projection.estimated_net_ownership_cost
        applicable = comparable and new_cost is not None and used_cost is not None
        price_difference = (
            new_projection.acquisition_cost - used_projection.acquisition_cost
            if comparable else None
        )
        expected_cost_difference = used_cost - new_cost if applicable else None

        break_even_target, break_even_discount = (None, None)
        if (
            applicable
            and new_projection.estimated_depreciation_percent is not None
            and used_projection.estimated_depreciation_percent is not None
        ):
            break_even_target, break_even_discount = self._break_even(
                product, new_option, used_option, horizon, options, new_cost
            )
        if break_even_target is not None and break_even_discount is not None:
            factors.extend([
                factor(
                    "break_even_target", "break_even", break_even_target, 0,
                    "bounded integer search from 0 to NEW acquisition cost",
                    "This is the highest USED acquisition cost whose applicable net ownership cost does not exceed NEW.",
                ),
                factor(
                    "break_even_discount", "break_even", break_even_discount, 0,
                    f"new_acquisition={new_projection.acquisition_cost:.2f}; target_used={break_even_target:.2f}",
                    "Break-even discount is derived from the numeric target, without summing embedded costs twice.",
                ),
            ])

        recommendation, recommended_id, reasons = self._recommend(
            new_option, used_option, new_projection, used_projection,
            confidence, comparable, applicable, break_even_target,
            expected_cost_difference,
        )
        if not applicable:
            confidence = max(0, confidence - 30)
        return OwnershipComparison(
            recommended_id, recommendation, confidence, projections,
            price_difference, expected_cost_difference, break_even_discount,
            break_even_target, factors, reasons, warnings,
        )

    def _depreciation(
        self, product: Product, option: PurchaseOption,
        horizon: OwnershipHorizon,
        comparison_options: Sequence[PurchaseOption],
    ) -> Tuple[Optional[float], List[OwnershipFactor], List[str]]:
        factors: List[OwnershipFactor] = []
        warnings: List[str] = []
        snapshot = option.market_snapshot
        depreciation: Optional[float] = None
        evidence = ""
        if horizon.months <= 0 or horizon.months > 24:
            warnings.append("V1 depreciation supports ownership horizons from 1 through 24 months.")
        elif option.purchase_type == PurchaseType.USED:
            if self._snapshot_valid(product, option, snapshot, "USED"):
                depreciation = (
                    snapshot.estimated_12_month_depreciation
                    if horizon.months <= 12
                    else snapshot.estimated_24_month_depreciation
                )
                evidence = f"USED market snapshot; horizon={horizon.months} months"
        else:
            used_option = next(
                (item for item in comparison_options if item.purchase_type == PurchaseType.USED),
                None,
            )
            used_snapshot = used_option.market_snapshot if used_option else None
            if (
                self._snapshot_valid(product, option, snapshot, "NEW")
                and used_option is not None
                and self._snapshots_compatible(snapshot, used_snapshot)
                and used_snapshot is not None
                and used_snapshot.segment == "USED"
                and snapshot.median_price is not None
                and snapshot.median_price > 0
                and used_snapshot.median_price is not None
                and used_snapshot.median_price > 0
            ):
                first_year = (1 - used_snapshot.median_price / snapshot.median_price) * 100
                if horizon.months <= 12:
                    depreciation = first_year
                    evidence = "NEW-to-USED median drop from compatible snapshots"
                else:
                    second_year = used_snapshot.estimated_12_month_depreciation
                    if second_year is not None and second_year <= 100:
                        depreciation = 100 * (
                            1 - (1 - first_year / 100) * (1 - second_year / 100)
                        )
                        evidence = "compounded NEW-to-USED first year and USED second-year depreciation"
        if depreciation is not None and depreciation > 100:
            warnings.append(
                f"Invalid depreciation above 100% was ignored: {depreciation:.2f}%."
            )
            depreciation = None
        if depreciation is None:
            factors.append(factor(
                "depreciation_unavailable", "depreciation", 0, 0,
                evidence or "compatible market depreciation unavailable",
                "No depreciation value is invented when compatible evidence is unavailable.", 40,
            ))
        else:
            factors.append(factor(
                "market_depreciation", "depreciation", depreciation, 0,
                evidence,
                "Depreciation comes directly from compatible market history; negative values represent appreciation.",
            ))
        return depreciation, factors, warnings

    def _resale_value(
        self, product: Product, option: PurchaseOption,
        horizon: OwnershipHorizon, cost: Optional[float],
        depreciation: Optional[float],
    ) -> Tuple[Optional[float], List[OwnershipFactor]]:
        factors: List[OwnershipFactor] = []
        if cost is None or depreciation is None:
            return None, factors
        resale = cost * (1 - depreciation / 100)
        factors.append(factor(
            "base_resale_value", "resale", depreciation, resale,
            f"acquisition={cost:.2f}; depreciation={depreciation:.2f}%",
            "Base resale value applies only the explicit market depreciation percentage.",
        ))
        reductions: List[Tuple[str, float, str]] = []
        if product.category.casefold() == "camera" and option.shutter_count is not None:
            if option.shutter_count >= 150_000:
                reductions.append(("shutter_resale_effect", 15, f"shutter_count={option.shutter_count}"))
            elif option.shutter_count >= 80_000:
                reductions.append(("shutter_resale_effect", 5, f"shutter_count={option.shutter_count}"))
        for defect in unique_defects(option.defects):
            if defect.severity.casefold() == "critical":
                reductions.append((
                    "defect_resale_effect", 40,
                    f"{defect.category}/{defect.severity}/{defect.affected_component}",
                ))
            elif defect.severity.casefold() == "major":
                reductions.append((
                    "defect_resale_effect", 20,
                    f"{defect.category}/{defect.severity}/{defect.affected_component}",
                ))
        if product.liquidity_score is not None:
            if product.liquidity_score < 40:
                reductions.append(("liquidity_resale_effect", 10, f"liquidity={product.liquidity_score}"))
            elif product.liquidity_score < 60:
                reductions.append(("liquidity_resale_effect", 5, f"liquidity={product.liquidity_score}"))
        for name, percent, evidence in reductions:
            impact = cost * percent / 100
            factors.append(factor(
                name, "resale", percent, -impact if horizon.planned_resale else 0,
                evidence,
                "This is a future resale-value effect, separate from ownership/repair risk."
                + (" It is applied because resale is planned." if horizon.planned_resale else " It is informational because resale is not planned."),
            ))
            if horizon.planned_resale:
                resale -= impact
        return max(0.0, resale), factors

    def _confidence(
        self, product: Product, option: PurchaseOption,
        cost: Optional[float], depreciation: Optional[float],
        unknown_accessories: int,
    ) -> Tuple[int, List[OwnershipFactor]]:
        confidence = 100
        factors: List[OwnershipFactor] = []

        def deduct(name: str, amount: int, evidence: str) -> None:
            nonlocal confidence
            confidence -= amount
            factors.append(factor(
                name, "confidence", amount, 0, evidence,
                f"Projection confidence is reduced by {amount} points.", 100,
            ))

        snapshot = option.market_snapshot
        if snapshot is None:
            deduct("missing_market_confidence", 25, "market snapshot unavailable")
        else:
            deduct(
                "market_confidence_adjustment",
                round((100 - max(0, min(100, snapshot.market_confidence))) * 0.25),
                f"market_confidence={snapshot.market_confidence}",
            )
        if depreciation is None:
            deduct("missing_depreciation_confidence", 20, "depreciation unavailable")
        if option.warranty_months is None:
            deduct("unknown_warranty_confidence", 10, "warranty status unknown")
        elif (
            option.purchase_type == PurchaseType.USED
            and option.warranty_months > 0
            and option.transferable_warranty is not True
        ):
            deduct("nontransferable_warranty_confidence", 5, "used warranty transferability unconfirmed")
        if option.return_window_days is None:
            deduct("unknown_return_confidence", 5, "return policy unknown")
        if option.condition_known is not True:
            deduct("unknown_condition_confidence", 15, "condition unknown")
        if product.category.casefold() == "camera" and option.shutter_count is None:
            deduct("missing_shutter_confidence", 10, "camera shutter count missing")
        if unknown_accessories:
            deduct(
                "accessory_coverage_confidence", min(10, unknown_accessories * 5),
                f"unvalued recognized accessories={unknown_accessories}",
            )
        if option.seller_reliability_score is None:
            deduct("seller_reliability_confidence", 10, "seller reliability unavailable")
        if option.invoice_available is None:
            deduct("invoice_provenance_confidence", 5, "invoice/proof-of-purchase status unknown")
        if cost is None:
            deduct("acquisition_cost_confidence", 30, "comparable acquisition cost unavailable")
        if option.contradictory:
            deduct("contradictory_input_confidence", 25, "ownership inputs contradict each other")
            confidence = min(confidence, 35)
        return max(0, min(100, confidence)), factors

    def _break_even(
        self, product: Product, new_option: PurchaseOption,
        used_option: PurchaseOption, horizon: OwnershipHorizon,
        options: Sequence[PurchaseOption], new_cost: float,
    ) -> Tuple[Optional[float], Optional[float]]:
        new_acquisition = acquisition_cost(new_option)
        if new_acquisition is None or new_cost is None:
            return None, None
        highest: Optional[float] = None
        for candidate in range(1, math.floor(new_acquisition) + 1):
            repriced = replace(
                used_option,
                purchase_price=float(candidate),
                estimated_landed_cost=(
                    float(candidate)
                    if used_option.estimated_landed_cost is not None else None
                ),
            )
            comparison_options = [
                repriced if item.option_id == used_option.option_id else item
                for item in options
            ]
            projection = self.project(
                product, repriced, horizon, comparison_options
            )
            candidate_cost = projection.estimated_net_ownership_cost
            if candidate_cost is not None and candidate_cost <= new_cost:
                highest = float(candidate)
        if highest is None:
            return None, None
        return highest, (new_acquisition - highest) / new_acquisition * 100

    @staticmethod
    def _recommend(
        new_option: PurchaseOption, used_option: PurchaseOption,
        new_projection: OwnershipProjection,
        used_projection: OwnershipProjection, confidence: int,
        comparable: bool, applicable: bool,
        break_even_target: Optional[float],
        expected_cost_difference: Optional[float],
    ) -> Tuple[OwnershipRecommendation, Optional[str], List[str]]:
        if new_projection.manual_review or used_projection.manual_review:
            return OwnershipRecommendation.MANUAL_REVIEW, None, [
                "Critical, contradictory, high-shutter, or major functional risk requires manual review."
            ]
        if not comparable or not applicable:
            return OwnershipRecommendation.INSUFFICIENT_DATA, None, [
                "Comparable currency, acquisition cost, depreciation, and applicable ownership costs are required."
            ]
        if confidence < 65:
            return OwnershipRecommendation.INSUFFICIENT_DATA, None, [
                "Ownership evidence confidence is below 65; the engine does not default to NEW."
            ]
        new_cost = new_projection.estimated_net_ownership_cost
        used_cost = used_projection.estimated_net_ownership_cost
        if new_cost is None or used_cost is None:
            return OwnershipRecommendation.INSUFFICIENT_DATA, None, [
                "Applicable ownership cost is unavailable."
            ]
        difference_ratio = abs(used_cost - new_cost) / max(abs(new_cost), abs(used_cost), 1)
        material_risk = used_projection.major_risk or (
            used_projection.acquisition_cost is not None
            and used_projection.risk_cost > used_projection.acquisition_cost * 0.15
        )
        if difference_ratio <= 0.03 and not material_risk:
            return OwnershipRecommendation.EQUIVALENT, None, [
                "Applicable net ownership costs are within 3% and neither option has material risk."
            ]
        current_used = used_projection.acquisition_cost
        if break_even_target is not None and current_used is not None:
            if current_used <= break_even_target and used_cost < new_cost and not material_risk:
                return OwnershipRecommendation.PREFER_USED, used_option.option_id, [
                    "USED is at or below the numeric break-even target and has lower applicable ownership cost."
                ]
            required_reduction = current_used - break_even_target
            if (
                required_reduction > 0
                and required_reduction <= current_used * 0.10
                and not used_projection.major_risk
            ):
                return OwnershipRecommendation.NEGOTIATE_USED, used_option.option_id, [
                    f"Reducing USED acquisition cost by {required_reduction:.2f} reaches the break-even target."
                ]
        falling = any(
            option.market_snapshot is not None
            and option.market_snapshot.market_confidence >= 60
            and option.market_snapshot.trend_30d is not None
            and option.market_snapshot.trend_30d <= -3
            for option in (new_option, used_option)
        )
        if falling:
            return OwnershipRecommendation.WAIT, None, [
                "A sufficiently confident market snapshot shows prices falling by at least 3% over 30 days."
            ]
        if expected_cost_difference is not None and expected_cost_difference > 0:
            return OwnershipRecommendation.PREFER_NEW, new_option.option_id, [
                "NEW has the lower applicable net ownership cost at current prices."
            ]
        return OwnershipRecommendation.PREFER_USED, used_option.option_id, [
            "USED has the lower applicable net ownership cost and no rule blocks it."
        ]

    @staticmethod
    def _snapshot_valid(
        product: Product, option: PurchaseOption,
        snapshot: Optional[MarketSnapshot], segment: str,
    ) -> bool:
        return bool(
            snapshot
            and snapshot.product_id == product.id
            and snapshot.segment == segment
            and snapshot.currency.casefold() == option.currency.casefold()
            and snapshot.market_confidence >= 40
            and (
                not option.target_market_country
                or snapshot.target_market_country.casefold()
                == option.target_market_country.casefold()
            )
        )

    @staticmethod
    def _snapshots_compatible(
        new: Optional[MarketSnapshot], used: Optional[MarketSnapshot]
    ) -> bool:
        return bool(
            new and used
            and new.product_id == used.product_id
            and new.currency.casefold() == used.currency.casefold()
            and new.target_market_country.casefold()
            == used.target_market_country.casefold()
            and new.market_confidence >= 40
            and used.market_confidence >= 40
        )

    @staticmethod
    def _unique(values: Sequence[str]) -> List[str]:
        return list(dict.fromkeys(value for value in values if value))
