"""Named, explicit economic rules for ownership projections."""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from catalog import Product
from connectors.models import ListingDefect

from .models import OwnershipFactor, PurchaseOption, PurchaseType


OPTICAL_RISK_CATEGORIES = {
    "optical_damage", "fungus", "haze", "cracks", "water_damage",
}
FUNCTIONAL_RISK_CATEGORIES = {"mechanical_damage", "electronic_damage"}


def factor(
    name: str, category: str, value: float, impact: float,
    evidence: str, explanation: str, confidence: int = 100,
) -> OwnershipFactor:
    return OwnershipFactor(
        name, category, value, impact, evidence, explanation, confidence
    )


def acquisition_cost(option: PurchaseOption) -> Optional[float]:
    if option.estimated_landed_cost is not None:
        return option.estimated_landed_cost if option.estimated_landed_cost > 0 else None
    if (
        option.source_country
        and option.target_market_country
        and option.source_country.casefold() == option.target_market_country.casefold()
        and option.purchase_price > 0
    ):
        return option.purchase_price
    return None


def protection_factors(
    option: PurchaseOption, cost: float,
    accessory_reference_prices: Mapping[str, float],
) -> Tuple[List[OwnershipFactor], int, float, int, List[str]]:
    factors: List[OwnershipFactor] = []
    warnings: List[str] = []
    warranty_percent = 0.0
    warranty_score = 0
    if option.warranty_months is not None and option.warranty_months > 0:
        if option.purchase_type == PurchaseType.NEW:
            warranty_percent = 8 if option.warranty_months >= 24 else (
                5 if option.warranty_months >= 12 else 2
            )
            warranty_score = 35 if option.warranty_months >= 24 else (
                25 if option.warranty_months >= 12 else 10
            )
        elif option.transferable_warranty is True:
            warranty_percent = 5 if option.warranty_months >= 12 else 2
            warranty_score = 25 if option.warranty_months >= 12 else 10
        else:
            warranty_score = 5
            warnings.append(
                "Used warranty information is preserved but has no monetary value because transferability is not confirmed."
            )
    warranty_value = min(cost * 0.08, cost * warranty_percent / 100)
    factors.append(factor(
        "warranty_protection_reference", "protection_reference", warranty_percent,
        warranty_value,
        f"months={option.warranty_months!r}; transferable={option.transferable_warranty!r}",
        f"Warranty has a non-cash reference value of {warranty_percent:.1f}% of acquisition cost.",
        100 if option.warranty_months is not None else 40,
    ))
    factors.append(factor(
        "warranty_protection_score", "protection_score", warranty_score,
        warranty_score,
        f"months={option.warranty_months!r}; transferable={option.transferable_warranty!r}",
        "Warranty duration and transferability contribute to the non-cash protection score.",
        100 if option.warranty_months is not None else 40,
    ))

    return_percent = 0.0
    return_score = 0
    if option.return_window_days is not None:
        return_percent = 2 if option.return_window_days >= 30 else (
            1 if option.return_window_days >= 14 else (
                0.5 if option.return_window_days >= 1 else 0
            )
        )
        return_score = 15 if option.return_window_days >= 30 else (
            10 if option.return_window_days >= 14 else (
                5 if option.return_window_days >= 1 else 0
            )
        )
    return_value = min(cost * 0.02, cost * return_percent / 100)
    combined_cap = cost * 0.10
    if warranty_value + return_value > combined_cap:
        return_value = max(0.0, combined_cap - warranty_value)
    factors.append(factor(
        "return_window_protection_reference", "protection_reference", return_percent,
        return_value, f"days={option.return_window_days!r}",
        f"Return rights have a non-cash reference value of {return_percent:.1f}% of acquisition cost.",
        100 if option.return_window_days is not None else 40,
    ))
    factors.append(factor(
        "return_window_protection_score", "protection_score", return_score,
        return_score, f"days={option.return_window_days!r}",
        "Return rights contribute to the non-cash protection score.",
        100 if option.return_window_days is not None else 40,
    ))

    accessory_factors, accessory_value, unknown_count = accessory_protection(
        option.accessories, cost, accessory_reference_prices
    )
    factors.extend(accessory_factors)
    factors.append(factor(
        "invoice_provenance", "protection_score", 10 if option.invoice_available else 0,
        10 if option.invoice_available else 0,
        f"invoice_available={option.invoice_available!r}",
        "Invoice evidence contributes to protection confidence but has no monetary reference value.",
        100 if option.invoice_available is not None else 50,
    ))
    factors.append(factor(
        "condition_provenance", "protection_score", 15 if option.condition_known else 0,
        15 if option.condition_known else 0,
        f"condition_known={option.condition_known!r}",
        "Known condition contributes to the protection score and is not monetized.",
        100 if option.condition_known is not None else 40,
    ))
    reliability_score = (
        round(15 * max(0.0, min(100.0, option.seller_reliability_score)) / 100)
        if option.seller_reliability_score is not None else 0
    )
    factors.append(factor(
        "seller_protection_score", "protection_score", reliability_score,
        reliability_score,
        f"seller_reliability_score={option.seller_reliability_score!r}",
        "Verified seller reliability contributes up to 15 points of non-cash protection.",
        100 if option.seller_reliability_score is not None else 40,
    ))
    zero_wear_score = 10 if option.purchase_type == PurchaseType.NEW else 0
    factors.append(factor(
        "zero_wear_protection_score", "protection_score", zero_wear_score,
        zero_wear_score, f"purchase_type={option.purchase_type.value}",
        "New-equipment zero-wear status contributes to protection score but has no monetary value.",
    ))
    protection_score = min(
        100,
        warranty_score + return_score
        + (10 if option.invoice_available else 0)
        + (15 if option.condition_known else 0)
        + reliability_score + zero_wear_score,
    )
    return (
        factors, protection_score,
        warranty_value + return_value + accessory_value,
        unknown_count, warnings,
    )


def accessory_protection(
    accessories: Sequence[str], cost: float,
    reference_prices: Mapping[str, float],
) -> Tuple[List[OwnershipFactor], float, int]:
    normalized_references = {
        _normalize(name): (name, max(0.0, price))
        for name, price in reference_prices.items()
    }
    seen: Dict[str, int] = {}
    factors: List[OwnershipFactor] = []
    recognized_total = 0.0
    unknown_count = 0
    for accessory in accessories:
        normalized = _normalize(accessory)
        reference = normalized_references.get(normalized)
        limit = 2 if "original" in normalized and "battery" in normalized else 1
        seen[normalized] = seen.get(normalized, 0) + 1
        if seen[normalized] > limit:
            factors.append(factor(
                "accessory_quantity_limit", "accessories", 0, 0,
                accessory,
                f"The duplicate accessory exceeds the V1 quantity limit of {limit} and receives no value.",
            ))
            continue
        if reference is None:
            unknown_count += 1
            factors.append(factor(
                "accessory_without_reference", "accessories", 0, 0,
                accessory,
                "No injected reference price matched this accessory; monetary value is zero.",
                50,
            ))
            continue
        reference_key, reference_price = reference
        recognized_total += reference_price
        factors.append(factor(
            "referenced_accessory", "protection_reference", reference_price,
            reference_price,
            f"accessory={accessory!r}; matched_reference={reference_key!r}",
            "The accessory uses its explicitly injected reference price.",
        ))
    cap = cost * 0.15
    protected = min(recognized_total, cap)
    if protected < recognized_total:
        factors.append(factor(
            "accessory_value_cap", "protection_reference", cap,
            -(recognized_total - protected),
            f"recognized_total={recognized_total:.2f}; cap={cap:.2f}",
            "The non-cash accessory reference value is capped at 15% of acquisition cost.",
        ))
    return factors, protected, unknown_count


def risk_factors(
    product: Product, option: PurchaseOption, cost: float,
) -> Tuple[List[OwnershipFactor], float, bool, bool]:
    factors: List[OwnershipFactor] = []
    total = 0.0
    manual_review = option.contradictory
    major_risk = False
    if option.condition_known is not True:
        impact = cost * 0.10
        total += impact
        factors.append(factor(
            "unknown_condition_risk", "risk_cost", 10, impact,
            f"condition_known={option.condition_known!r}",
            "Unknown condition adds a 10% expected ownership-risk cost.", 60,
        ))
    if product.category.casefold() == "camera" and option.shutter_count is not None:
        shutter_percent = (
            15 if option.shutter_count >= 150_000 else
            7 if option.shutter_count >= 80_000 else
            3 if option.shutter_count >= 40_000 else
            1 if option.shutter_count >= 10_000 else 0
        )
        impact = cost * shutter_percent / 100
        total += impact
        factors.append(factor(
            "shutter_ownership_risk", "risk_cost", shutter_percent, impact,
            f"shutter_count={option.shutter_count}",
            "This general camera-lifecycle heuristic represents ownership risk, not resale loss.",
        ))
        if option.shutter_count >= 150_000:
            manual_review = True

    for defect in unique_defects(option.defects):
        percent, defect_manual, defect_major = defect_risk(defect)
        impact = cost * percent / 100
        total += impact
        factors.append(factor(
            "defect_ownership_risk", "risk_cost", percent, impact,
            f"category={defect.category}; severity={defect.severity}; component={defect.affected_component}",
            "This factor represents expected ownership or repair exposure for one deduplicated defect.",
            round(defect.confidence * 100),
        ))
        manual_review = manual_review or defect_manual
        major_risk = major_risk or defect_major

    if option.seller_reliability_score is not None:
        reliability = max(0.0, min(100.0, option.seller_reliability_score))
        percent = 5 * (100 - reliability) / 100
        impact = cost * percent / 100
        total += impact
        factors.append(factor(
            "seller_reliability_risk", "risk_cost", percent, impact,
            f"seller_reliability_score={reliability:.1f}",
            "Seller uncertainty contributes at most 5% expected ownership risk.",
        ))
    missing_percent = min(10, len(option.missing_information) * 2)
    if missing_percent:
        impact = cost * missing_percent / 100
        total += impact
        factors.append(factor(
            "incomplete_information_risk", "risk_cost", missing_percent,
            impact, "; ".join(option.missing_information),
            "Each missing ownership input adds 2% risk, capped at 10%.", 60,
        ))
    if option.contradictory:
        factors.append(factor(
            "contradictory_input_review", "review", 1, 0,
            "contradictory=True",
            "Contradictory ownership evidence requires manual review and is not assigned a hidden economic value.",
            20,
        ))
    return factors, total, manual_review, major_risk


def defect_risk(defect: ListingDefect) -> Tuple[float, bool, bool]:
    category = defect.category.casefold()
    severity = defect.severity.casefold()
    if category == "cosmetic_damage":
        percent = {"minor": 0, "moderate": 1, "major": 3, "critical": 8}.get(severity, 1)
        structural = severity == "critical" and any(
            term in _normalize(f"{defect.affected_component} {defect.description}")
            for term in ("structural", "integrity", "frame", "chassis", "crack")
        )
        return percent, structural, False
    if category in OPTICAL_RISK_CATEGORIES:
        percent = {"minor": 15, "unknown": 15, "moderate": 20, "major": 30, "critical": 40}.get(severity, 15)
        return percent, severity in {"major", "critical"}, severity in {"major", "critical"}
    if category in FUNCTIONAL_RISK_CATEGORIES:
        percent = {"minor": 5, "moderate": 10, "major": 20, "critical": 40}.get(severity, 10)
        return percent, severity in {"major", "critical"}, severity in {"major", "critical"}
    percent = {"minor": 3, "moderate": 8, "major": 20, "critical": 40}.get(severity, 8)
    return percent, severity == "critical", severity in {"major", "critical"}


def unique_defects(defects: Sequence[ListingDefect]) -> List[ListingDefect]:
    result: List[ListingDefect] = []
    seen = set()
    for defect in defects:
        key = tuple(_normalize(value) for value in (
            defect.category, defect.severity, defect.affected_component,
            defect.description,
        ))
        if key not in seen:
            seen.add(key)
            result.append(defect)
    return result


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
