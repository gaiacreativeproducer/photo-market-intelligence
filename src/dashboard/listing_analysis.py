"""Adapt persisted radar listings to existing analysis engines for the dashboard."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from catalog import Product
from connectors.models import (
    DEFECT_CATEGORIES, DEFECT_SEVERITIES, Listing, ListingDefect,
)
from decision import DecisionEngine, MarketStatistics, NewAlternative
from market import MarketEngine, MarketSnapshot
from ownership import (
    OwnershipEngine, OwnershipHorizon, PurchaseOption, PurchaseType,
)
from radar.models import RadarListing
from .conclusions import build_overall_conclusion, market_sample_label


ACCEPTED_RECOGNITION_CONFIDENCE = 70


def analyze_listings(
    products: Sequence[Product], listings: Sequence[RadarListing],
    manually_assigned_listing_ids: Sequence[str] = (),
) -> Dict[str, Dict[str, object]]:
    """Return dashboard-safe analysis grouped by product ID."""
    products_by_id = {product.id: product for product in products}
    active = [listing for listing in listings if listing.active]
    manual = set(manually_assigned_listing_ids)
    review = {
        listing.listing_id: (
            requires_structural_review(listing)
            if listing.listing_id in manual else needs_review(listing, products_by_id)
        )
        for listing in listings
    }
    connector_listings = {listing.listing_id: _connector_listing(listing) for listing in listings}
    result: Dict[str, Dict[str, object]] = {}
    for product_id in sorted({item.product_id for item in active if item.product_id}):
        product = products_by_id.get(product_id)
        if product is None:
            continue
        compatible = [
            item for item in active
            if item.product_id == product_id and not review[item.listing_id]
        ]
        snapshots = _snapshots(product, compatible, connector_listings)
        decisions = {
            item.listing_id: _decision(
                product, item, connector_listings[item.listing_id], snapshots,
                compatible,
            )
            for item in compatible
        }
        comparisons, default_key = _comparisons(
            product, compatible, connector_listings, snapshots
        )
        market_summary = _market_summary(snapshots)
        default_comparison = comparisons.get(default_key) if default_key else None
        comparison_conclusions = {
            key: build_overall_conclusion(decisions, comparison, market_summary, compatible)
            for key, comparison in comparisons.items()
        }
        result[product_id] = {
            "market": market_summary,
            "decisions": decisions,
            "comparisons": comparisons,
            "default_comparison_key": default_key,
            "comparison_options": [
                _option_summary(item) for item in sorted(compatible, key=_offer_rank)
            ],
            "overall_conclusion": build_overall_conclusion(
                decisions, default_comparison, market_summary, compatible
            ),
            "comparison_conclusions": comparison_conclusions,
        }
    return result


def needs_review(
    listing: RadarListing, products_by_id: Mapping[str, Product]
) -> bool:
    """Apply the public review rule without inferring from storage status."""
    return bool(
        not listing.product_id
        or listing.product_id not in products_by_id
        or listing.recognition_confidence < ACCEPTED_RECOGNITION_CONFIDENCE
        or requires_structural_review(listing)
    )


def requires_structural_review(listing: RadarListing) -> bool:
    """Return review state that a manual product assignment cannot override."""
    return _contradictory(listing) or _invalid_defects(listing)


def listing_view(
    listing: RadarListing, products_by_id: Mapping[str, Product],
    analysis: Mapping[str, Dict[str, object]],
) -> Dict[str, object]:
    review = needs_review(listing, products_by_id)
    product = products_by_id.get(listing.product_id)
    product_analysis = analysis.get(listing.product_id, {})
    decision = product_analysis.get("decisions", {}).get(listing.listing_id)
    return {
        "listing_id": listing.listing_id,
        "product_id": listing.product_id or None,
        "product_name": _product_name(product) if product else "Da verificare",
        "title": listing.title,
        "source": listing.source_name,
        "segment": listing.segment,
        "price": listing.price,
        "currency": listing.currency,
        "country": listing.source_country,
        "marketplace": listing.marketplace_id or None,
        "original_condition": listing.original_condition or None,
        "buying_options": list(listing.buying_options),
        "auction": "AUCTION" in listing.buying_options,
        "shipping_cost": listing.shipping_cost,
        "shipping_currency": listing.shipping_currency or None,
        "item_location_country": listing.item_location_country or None,
        "market_stats_eligible": listing.market_stats_eligible,
        "recognition_confidence": listing.recognition_confidence,
        "description_confidence": listing.description_confidence,
        "shutter_count": listing.shutter_count,
        "warranty_status": _warranty_label(listing),
        "warranty_until": listing.warranty_until,
        "defects": list(listing.defects),
        "accessories": list(listing.accessories),
        "first_seen": listing.first_seen_at.isoformat(),
        "last_seen": listing.last_seen_at.isoformat(),
        "active": listing.active,
        "needs_review": review,
        "analysis_status": "Da verificare" if review else "Analizzato",
        "url": listing.url,
        "decision": decision,
    }


def _snapshots(
    product: Product, listings: Sequence[RadarListing],
    converted: Mapping[str, Listing],
) -> Dict[Tuple[str, str], MarketSnapshot]:
    snapshots: Dict[Tuple[str, str], MarketSnapshot] = {}
    for currency, segment in sorted({(item.currency, item.segment) for item in listings}):
        candidates = [
            item for item in listings
            if item.currency == currency and item.segment == segment
        ]
        if not candidates:
            continue
        target_country = sorted(item.source_country for item in candidates)[0]
        evidence = _market_evidence(candidates)
        engine = MarketEngine(
            target_country, currency, segment,
            recognized_product_ids=evidence["product_ids"],
            recognition_confidence=evidence["recognition"],
            description_confidence=evidence["description"],
            description_contradictions=evidence["contradictions"],
            description_evidence_count=evidence["evidence_count"],
            listing_segments=evidence["segments"],
            source_countries=evidence["countries"],
            warranty_clarity=evidence["warranty"],
            accessory_completeness=evidence["accessories"],
            statistical_eligibility=evidence["statistical_eligibility"],
            created_at=max(item.last_seen_at for item in candidates),
        )
        snapshots[(currency, segment)] = engine.build_snapshot(
            product, [converted[item.listing_id] for item in candidates]
        )
    return snapshots


def _market_evidence(listings: Sequence[RadarListing]) -> Dict[str, Dict[str, object]]:
    return {
        "product_ids": {item.listing_id: item.product_id for item in listings},
        "recognition": {item.listing_id: item.recognition_confidence for item in listings},
        "description": {item.listing_id: item.description_confidence for item in listings},
        "contradictions": {item.listing_id: _contradictory(item) for item in listings},
        "evidence_count": {item.listing_id: _evidence_count(item) for item in listings},
        "segments": {item.listing_id: item.segment for item in listings},
        "countries": {item.listing_id: item.source_country for item in listings},
        "warranty": {item.listing_id: _warranty_known(item) for item in listings},
        "accessories": {item.listing_id: True for item in listings},
        "statistical_eligibility": {item.listing_id: item.market_stats_eligible for item in listings},
    }


def _decision(
    product: Product, radar: RadarListing, listing: Listing,
    snapshots: Mapping[Tuple[str, str], MarketSnapshot],
    compatible: Sequence[RadarListing],
) -> Dict[str, object]:
    used = snapshots.get((radar.currency, "USED"))
    new = snapshots.get((radar.currency, "NEW"))
    market = MarketStatistics(
        used.median_price if used else None,
        used.lowest_price if used else None,
        new.median_price if new else None,
        used.valid_sample_size if used else 0,
        used.trend_30d if used else None,
        30,
        radar.currency,
    ) if used or new else None
    new_listing = _select_offer(
        [item for item in compatible if item.currency == radar.currency and item.segment == "NEW"]
    )
    alternative = None
    if radar.segment == "USED" and new_listing and new_listing.price is not None:
        alternative = NewAlternative(
            new_listing.price, new_listing.currency,
            _warranty_months(new_listing) or 0, 0, 50,
            "Derived from an active, comparable dashboard listing.",
        )
    report = DecisionEngine(as_of=radar.detected_at.date()).evaluate(
        product, listing, market, alternative
    )
    return {
        "recommendation": report.recommendation.value,
        "buy_score": report.buy_score,
        "confidence": report.confidence,
        "fair_price": report.expected_fair_price,
        "new_vs_used_recommendation": report.new_vs_used_recommendation.value,
        "estimated_used_advantage": report.estimated_used_advantage,
        "reasons": list(report.reasons),
        "warnings": list(report.warnings),
        "missing_information": list(report.missing_information),
    }


def _comparisons(
    product: Product, listings: Sequence[RadarListing],
    converted: Mapping[str, Listing],
    snapshots: Mapping[Tuple[str, str], MarketSnapshot],
) -> Tuple[Dict[str, Dict[str, object]], Optional[str]]:
    new_items = [item for item in listings if item.segment == "NEW"]
    used_items = [item for item in listings if item.segment == "USED"]
    comparisons: Dict[str, Dict[str, object]] = {}
    for new_item in sorted(new_items, key=_offer_rank):
        for used_item in sorted(used_items, key=_offer_rank):
            if new_item.currency != used_item.currency:
                continue
            key = _comparison_key(new_item.listing_id, used_item.listing_id)
            options = [
                _purchase_option(new_item, PurchaseType.NEW, snapshots, converted),
                _purchase_option(used_item, PurchaseType.USED, snapshots, converted),
            ]
            report = OwnershipEngine().compare(
                product, options, OwnershipHorizon(12, "normal", False)
            )
            comparisons[key] = _ownership_summary(report, new_item, used_item)
    default_key = next(iter(comparisons), None)
    return comparisons, default_key


def _purchase_option(
    radar: RadarListing, purchase_type: PurchaseType,
    snapshots: Mapping[Tuple[str, str], MarketSnapshot],
    converted: Mapping[str, Listing],
) -> PurchaseOption:
    listing = converted[radar.listing_id]
    months = _warranty_months(radar)
    missing = list(radar.missing_information)
    if _explicit_no_warranty(radar):
        missing = [value for value in missing if value.casefold() != "warranty status"]
    return PurchaseOption(
        radar.listing_id, purchase_type, float(radar.price or 0), radar.currency,
        months, 0 if months == 0 else None, None, radar.shutter_count,
        list(listing.defects), list(radar.accessories), 50,
        snapshots.get((radar.currency, radar.segment)), "",
        radar.source_country, radar.source_country,
        True if purchase_type == PurchaseType.NEW and months else None,
        radar.invoice_available, bool(radar.condition or radar.segment),
        _contradictory(radar), missing,
    )


def _ownership_summary(report, new_item: RadarListing, used_item: RadarListing) -> Dict[str, object]:
    projections = {item.option_id: item for item in report.projections}
    new_projection = projections.get(new_item.listing_id)
    used_projection = projections.get(used_item.listing_id)
    difference = (
        new_item.price - used_item.price
        if new_item.price is not None and used_item.price is not None else None
    )
    percent = (
        difference / new_item.price * 100
        if difference is not None and new_item.price else None
    )
    return {
        "new_listing_id": new_item.listing_id,
        "used_listing_id": used_item.listing_id,
        "currency": new_item.currency,
        "new_price": new_item.price,
        "used_price": used_item.price,
        "nominal_saving": difference,
        "saving_percentage": percent,
        "recommendation": report.recommendation.value,
        "confidence": report.confidence,
        "break_even_used_price": report.break_even_target_used_price,
        "new_projection": _projection_summary(new_projection),
        "used_projection": _projection_summary(used_projection),
        "reasons": list(report.reasons),
        "warnings": list(report.warnings),
    }


def _projection_summary(projection) -> Optional[Dict[str, object]]:
    if projection is None:
        return None
    return {
        "gross_cost_with_resale": projection.gross_ownership_cost_with_resale,
        "gross_cost_without_resale": projection.gross_ownership_cost_without_resale,
        "risk_cost": projection.risk_cost,
        "protection_score": projection.protection_score,
        "estimated_resale_value": projection.estimated_resale_value,
        "confidence": projection.confidence,
        "warnings": list(projection.warnings),
        "missing_information": list(projection.missing_information),
    }


def _market_summary(snapshots: Mapping[Tuple[str, str], MarketSnapshot]) -> Dict[str, object]:
    values: Dict[str, object] = {}
    for (currency, segment), snapshot in sorted(snapshots.items()):
        values[f"{currency}:{segment}"] = {
            "currency": currency,
            "segment": segment,
            "sample_size": snapshot.sample_size,
            "valid_sample_size": snapshot.valid_sample_size,
            "median": snapshot.median_price,
            "lowest": snapshot.lowest_price,
            "highest": snapshot.highest_price,
            "market_confidence": snapshot.market_confidence,
            "outlier_count": snapshot.outlier_count,
            "sample_label": market_sample_label(snapshot.valid_sample_size),
            "price_label": "Prezzo osservato" if snapshot.valid_sample_size == 1 else "Mediana di mercato",
            "notes": list(snapshot.notes),
        }
    return values


def _connector_listing(item: RadarListing) -> Listing:
    defects = [_listing_defect(value) for value in item.defects]
    missing = list(item.missing_information)
    warranty_until = item.warranty_until
    if _explicit_no_warranty(item):
        warranty_until = item.detected_at.date().isoformat()
        missing = [value for value in missing if value.casefold() != "warranty status"]
    return Listing(
        item.listing_id, item.source_name, item.title, item.url, item.price,
        item.currency, item.condition or item.segment, item.source_country, "",
        item.description, item.detected_at, {}, item.source_id,
        item.shutter_count, warranty_until, item.invoice_available,
        item.original_box_available, item.accessories, defects,
        item.seller_claims, missing,
        item.marketplace_id, item.original_condition, list(item.buying_options),
        item.shipping_cost, item.shipping_currency, item.item_location_country,
        item.market_stats_eligible,
    )


def _listing_defect(value: Mapping[str, object]) -> ListingDefect:
    try:
        confidence = float(value.get("confidence", -1))
    except (TypeError, ValueError):
        confidence = -1
    return ListingDefect(
        str(value.get("category", "unknown")),
        str(value.get("description", "")),
        str(value.get("severity", "unknown")),
        str(value.get("affected_component", "")),
        str(value.get("source_text", "")), confidence,
    )


def _invalid_defects(item: RadarListing) -> bool:
    for defect in item.defects:
        try:
            confidence = float(defect.get("confidence", -1))
        except (TypeError, ValueError):
            return True
        if (
            defect.get("category") not in DEFECT_CATEGORIES
            or defect.get("severity") not in DEFECT_SEVERITIES
            or not str(defect.get("description", "")).strip()
            or not 0 <= confidence <= 1
        ):
            return True
    return False


def _contradictory(item: RadarListing) -> bool:
    return any("contradict" in warning.casefold() for warning in item.warnings)


def _evidence_count(item: RadarListing) -> int:
    return sum((
        item.shutter_count is not None, item.warranty_until is not None,
        item.invoice_available is not None, item.original_box_available is not None,
        bool(item.defects), bool(item.accessories), bool(item.seller_claims),
    ))


def _warranty_known(item: RadarListing) -> bool:
    return item.warranty_until is not None or _explicit_no_warranty(item)


def _explicit_no_warranty(item: RadarListing) -> bool:
    text = f"{item.title} {item.description}".casefold()
    return bool(re.search(r"\b(?:senza garanzia|no warranty|without warranty)\b", text))


def _warranty_months(item: RadarListing) -> Optional[int]:
    if _explicit_no_warranty(item):
        return 0
    if not item.warranty_until:
        return None
    try:
        end = date.fromisoformat(item.warranty_until)
    except ValueError:
        return None
    days = (end - item.detected_at.date()).days
    return max(0, int(math.ceil(days / 30)))


def _warranty_label(item: RadarListing) -> str:
    months = _warranty_months(item)
    if months is None:
        return "Garanzia non specificata"
    if months == 0:
        return "Senza garanzia attiva"
    return f"Garanzia attiva fino al {item.warranty_until}"


def _offer_rank(item: RadarListing) -> Tuple[object, ...]:
    return (
        -item.recognition_confidence, -item.description_confidence,
        item.price if item.price is not None else float("inf"),
        -item.last_seen_at.timestamp(), item.listing_id,
    )


def _select_offer(items: Sequence[RadarListing]) -> Optional[RadarListing]:
    return min(items, key=_offer_rank) if items else None


def _comparison_key(new_id: str, used_id: str) -> str:
    return f"{new_id}:{used_id}"


def _option_summary(item: RadarListing) -> Dict[str, object]:
    return {
        "listing_id": item.listing_id, "segment": item.segment,
        "title": item.title, "price": item.price, "currency": item.currency,
    }


def _product_name(product: Optional[Product]) -> str:
    if product is None:
        return "Da verificare"
    return " ".join(value for value in (product.brand, product.model, product.version) if value)
