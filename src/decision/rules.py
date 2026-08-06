"""Named, explicit scoring rules for Decision Engine V1."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import List, Optional, Sequence, Tuple

from catalog import Product
from connectors.models import DEFECT_CATEGORIES, DEFECT_SEVERITIES, Listing

from .models import DecisionFactor, MarketStatistics


OPTICAL_RISK_CATEGORIES = {
    "optical_damage", "fungus", "haze", "scratches", "cracks", "water_damage"
}
KNOWN_ACCESSORY_BRANDS = {
    "sony", "nikon", "canon", "panasonic", "sigma", "tamron", "smallrig",
    "nisi", "hoya", "tiffen", "b+w", "dji", "manfrotto", "lowepro",
}


def factor(name: str, category: str, impact: int, evidence: str,
           explanation: str, confidence: int = 100) -> DecisionFactor:
    return DecisionFactor(name, category, impact, evidence, explanation, confidence)


def evaluate_market_price(
    listing: Listing, market: Optional[MarketStatistics]
) -> List[DecisionFactor]:
    if listing.price is None or not market or market.median_used_price is None:
        return []
    if not _matching_currency(listing.currency, market.currency):
        return []
    median = market.median_used_price
    if median <= 0:
        return []
    difference = (median - listing.price) / median * 100
    if difference >= 20:
        impact = 25
    elif difference >= 10:
        impact = 15
    elif difference > 5:
        impact = 7
    elif difference >= -5:
        impact = 0
    elif difference > -10:
        impact = -8
    elif difference > -20:
        impact = -18
    else:
        impact = -30
    return [factor(
        "price_vs_used_market", "price", impact,
        f"listing={listing.price:.2f} {listing.currency}; median={median:.2f} {market.currency}; difference={difference:.2f}%",
        f"The listing is {abs(difference):.2f}% {'below' if difference >= 0 else 'above'} the used-market median.",
    )]


def evaluate_condition(listing: Listing) -> Tuple[List[DecisionFactor], List[str]]:
    missing = list(listing.missing_information)
    condition_missing = not listing.condition.strip() or listing.condition.casefold() in {"unknown", "not specified"}
    if condition_missing and "condition details" not in missing:
        missing.append("condition details")
    if not condition_missing:
        return [], missing
    return [factor(
        "unknown_condition", "condition", -5, "condition details unavailable",
        "Unknown condition increases purchase risk and requires clarification.", 60,
    )], missing


def evaluate_defects(
    listing: Listing,
) -> Tuple[List[DecisionFactor], List[str], bool, bool, bool]:
    factors: List[DecisionFactor] = []
    warnings: List[str] = []
    manual_review = False
    must_pass = False
    major_or_critical = False
    cosmetic = {"minor": -3, "moderate": -8, "major": -15, "critical": -30}
    optical = {"minor": -25, "moderate": -30, "major": -40, "critical": -50}
    other = {"minor": -5, "moderate": -12, "major": -20, "critical": -30}
    dust = {"minor": -2, "moderate": -5, "major": -12, "critical": -25}

    for index, defect in enumerate(listing.defects, start=1):
        invalid = []
        if defect.category not in DEFECT_CATEGORIES:
            invalid.append(f"invalid category {defect.category!r}")
        if defect.severity not in DEFECT_SEVERITIES:
            invalid.append(f"invalid severity {defect.severity!r}")
        if not defect.description.strip():
            invalid.append("missing description")
        if not 0 <= defect.confidence <= 1:
            invalid.append(f"confidence {defect.confidence!r} outside 0..1")
        if invalid:
            message = f"Defect {index} has invalid structured data: {', '.join(invalid)}."
            warnings.append(message)
            factors.append(factor(
                f"invalid_defect_{index}", "defect", 0, repr(defect), message, 20
            ))
            manual_review = True
            continue
        if defect.category == "unknown" or defect.severity == "unknown":
            impact = -5
            manual_review = True
            warnings.append(f"Defect severity or category is unknown: {defect.description}.")
        elif defect.category == "cosmetic_damage":
            impact = cosmetic[defect.severity]
            manual_review = defect.severity == "critical"
        elif defect.category in OPTICAL_RISK_CATEGORIES:
            impact = optical[defect.severity]
            manual_review = True
            must_pass = defect.severity == "critical"
        elif defect.category == "dust":
            impact = dust[defect.severity]
            manual_review = manual_review or defect.severity == "critical"
        else:
            impact = other[defect.severity]
            manual_review = manual_review or defect.severity == "critical"
        major_or_critical = major_or_critical or defect.severity in {"major", "critical"}
        factors.append(factor(
            f"defect_{index}_{defect.category}", "defect", impact,
            f"category={defect.category}; severity={defect.severity}; component={defect.affected_component}; confidence={defect.confidence:.2f}",
            f"{defect.description} produces an explicit {impact}-point risk adjustment.",
            round(defect.confidence * 100),
        ))
    return factors, warnings, manual_review, must_pass, major_or_critical


def evaluate_shutter_count(
    product: Product, listing: Listing
) -> List[DecisionFactor]:
    if product.category.casefold() != "camera" or listing.shutter_count is None:
        return []
    count = listing.shutter_count
    if count < 10_000:
        impact = 5
    elif count < 40_000:
        impact = 2
    elif count < 80_000:
        impact = -5
    elif count < 150_000:
        impact = -12
    else:
        impact = -25
    return [factor(
        "shutter_count", "condition", impact, f"shutter_count={count}",
        "Shutter count is used as a general risk heuristic; no universal shutter life is assumed.",
    )]


def parse_warranty(value: Optional[str], as_of: date) -> Optional[date]:
    if not value:
        return None
    for pattern in ("%Y-%m-%d", "%B %Y"):
        try:
            parsed = datetime.strptime(value, pattern).date()
            if pattern == "%B %Y":
                parsed = date(parsed.year, parsed.month, 28)
            return parsed
        except ValueError:
            continue
    return None


def evaluate_warranty(
    listing: Listing, as_of: date
) -> Tuple[List[DecisionFactor], bool, bool]:
    warranty_date = parse_warranty(listing.warranty_until, as_of)
    if warranty_date is None:
        return [], False, True
    if warranty_date <= as_of:
        return [factor(
            "expired_warranty", "protection", 0, f"warranty_until={listing.warranty_until}",
            "The stated warranty is expired and adds no protected value.",
        )], False, False
    months = (warranty_date.year - as_of.year) * 12 + warranty_date.month - as_of.month
    impact = 8 if months >= 12 else 4
    return [factor(
        "active_warranty", "protection", impact,
        f"warranty_until={listing.warranty_until}; approximately {months} months remaining",
        f"Active warranty adds {impact} points of protected value.",
    )], True, False


def evaluate_documentation(listing: Listing) -> List[DecisionFactor]:
    factors = []
    if listing.invoice_available is True:
        factors.append(factor("invoice", "documentation", 3, "invoice available", "An invoice improves provenance and warranty usability."))
    if listing.original_box_available is True:
        factors.append(factor("original_box", "documentation", 2, "original box available", "The original box supports completeness and resale."))
    return factors


def evaluate_accessories(
    product: Product, accessories: Sequence[str]
) -> Tuple[List[DecisionFactor], int]:
    factors: List[DecisionFactor] = []
    battery_bonus = 0
    total = 0
    for index, item in enumerate(accessories, start=1):
        normalized = item.casefold()
        impact = 0
        reason = "The accessory is unknown or unverifiable and receives no bonus."
        if "original" in normalized and "battery" in normalized and battery_bonus < 6:
            impact = min(3, 6 - battery_bonus)
            battery_bonus += impact
            reason = "Recognized as an original battery."
        elif "grip" in normalized and "original" in normalized and product.brand.casefold() in normalized:
            impact = 5
            reason = "Recognized as an original manufacturer grip."
        elif "filter" in normalized:
            if _verified_item(normalized, "filter"):
                impact, reason = 2, "Filter has identifiable brand and model text."
            else:
                reason = "Filter lacks identifiable brand and model text."
        elif "cage" in normalized and _verified_item(normalized, "cage"):
            impact, reason = 3, "Cage has identifiable brand and model text."
        elif "charger" in normalized and _verified_item(normalized, "charger"):
            impact, reason = 2, "Charger has identifiable brand and model text."
        elif "bag" in normalized and _verified_item(normalized, "bag"):
            impact, reason = 1, "Bag has identifiable brand and model text."
        allowed = max(0, 12 - total)
        applied = min(impact, allowed)
        total += applied
        factors.append(factor(
            f"accessory_{index}", "accessories", applied, item,
            f"{reason} Applied bonus: {applied}.", 90 if applied else 60,
        ))
    return factors, total


def resale_score(product: Product) -> Optional[int]:
    value = product.liquidity_score
    if value is None:
        return None
    if value >= 80:
        return 90
    if value >= 60:
        return 75
    if value >= 40:
        return 55
    return 30


def wait_probability(
    listing: Listing, market: Optional[MarketStatistics]
) -> Optional[int]:
    if not market or market.sample_size < 3 or not _matching_currency(listing.currency, market.currency):
        return None
    probability = 25.0
    if market.price_trend_percent is not None:
        if market.price_trend_percent < 0:
            probability += min(30, abs(market.price_trend_percent) * 2)
        elif market.price_trend_percent > 0:
            probability -= min(15, market.price_trend_percent)
    if listing.price is not None and market.lowest_recent_used_price is not None and listing.price < market.lowest_recent_used_price:
        probability -= 15
    if market.replacement_model_released is True:
        probability += 15
    return round(max(0, min(100, probability)))


def _matching_currency(left: Optional[str], right: Optional[str]) -> bool:
    return bool(left and right and left.casefold() == right.casefold())


def _verified_item(text: str, category: str) -> bool:
    has_brand = any(re.search(rf"\b{re.escape(brand)}\b", text) for brand in KNOWN_ACCESSORY_BRANDS)
    without_category = text.replace(category, " ")
    has_model = bool(re.search(r"\b(?=\w*[a-z])(?=\w*\d)[a-z0-9+.-]+\b", without_category))
    return has_brand and has_model
