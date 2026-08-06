"""Listing quality, validation, duplicate handling, and outlier visibility."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Dict, List, Mapping, Optional, Sequence

from connectors.models import Listing

from .models import ExclusionReason, MarketObservation
from .statistics import iqr_fences


@dataclass(frozen=True)
class MarketEvidence:
    recognized_product_ids: Mapping[str, Optional[str]]
    recognition_confidence: Mapping[str, int]
    description_confidence: Mapping[str, int]
    description_contradictions: Mapping[str, bool]
    description_evidence_count: Mapping[str, int]
    listing_segments: Mapping[str, str]
    source_countries: Mapping[str, str]
    landed_costs: Mapping[str, float]
    warranty_clarity: Mapping[str, bool]
    accessory_completeness: Mapping[str, bool]


def listing_quality(listing: Listing, evidence: MarketEvidence) -> int:
    listing_id = listing.external_id
    if listing.price is None or listing.price <= 0:
        return 0
    score = 100
    recognition = evidence.recognition_confidence.get(listing_id)
    score -= 20 if recognition is None else round((100 - _clamp(recognition)) * 0.20)
    description = evidence.description_confidence.get(listing_id)
    score -= 15 if description is None else round((100 - _clamp(description)) * 0.15)
    if not listing.condition.strip() or listing.condition.strip().casefold() in {
        "unknown", "not specified",
    }:
        score -= 15
    score -= min(20, 5 * len(listing.missing_information))
    if not evidence.warranty_clarity.get(listing_id, listing.warranty_until is not None):
        score -= 10
    if not evidence.accessory_completeness.get(listing_id, False):
        score -= 5
    if evidence.description_contradictions.get(listing_id, False):
        score -= 25
    if any(
        not defect.description.strip()
        or not defect.affected_component.strip()
        or not defect.severity.strip()
        for defect in listing.defects
    ):
        score -= 10
    return _clamp(score)


def clean_listings(
    listings: Sequence[Listing], product_id: str,
    target_market_country: str, currency: str, segment: str,
    evidence: MarketEvidence,
) -> List[MarketObservation]:
    observations = [
        _observation(
            listing, product_id, target_market_country, currency, segment, evidence
        )
        for listing in listings
    ]
    observations = _mark_duplicates(listings, observations)
    return _mark_outliers(observations)


def _observation(
    listing: Listing, product_id: str, target_market_country: str,
    currency: str, segment: str, evidence: MarketEvidence,
) -> MarketObservation:
    listing_id = listing.external_id
    source_country = evidence.source_countries.get(listing_id)
    listing_segment = evidence.listing_segments.get(listing_id)
    listed_price = listing.price
    explicit_landed = evidence.landed_costs.get(listing_id)
    domestic = (
        source_country is not None
        and source_country.casefold() == target_market_country.casefold()
    )
    landed_cost = explicit_landed if explicit_landed is not None else (
        listed_price if domestic else None
    )
    statistical_price = landed_cost if landed_cost is not None else (
        listed_price if domestic else None
    )
    reason: Optional[ExclusionReason] = None
    if listed_price is None or listed_price <= 0:
        reason = ExclusionReason.MISSING_PRICE
    elif listing.currency.casefold() != currency.casefold():
        reason = ExclusionReason.WRONG_CURRENCY
    elif evidence.recognized_product_ids.get(listing_id) != product_id:
        reason = ExclusionReason.PRODUCT_NOT_CONFIRMED
    elif listing_segment is None:
        reason = ExclusionReason.INSUFFICIENT_INFORMATION
    elif listing_segment.upper() != segment:
        reason = ExclusionReason.SEGMENT_MISMATCH
    elif source_country is None:
        reason = ExclusionReason.INSUFFICIENT_INFORMATION
    elif not domestic and landed_cost is None:
        reason = ExclusionReason.LANDED_COST_UNKNOWN
    elif any(defect.severity in {"major", "critical"} for defect in listing.defects):
        reason = ExclusionReason.SEVERE_DAMAGE
    return MarketObservation(
        listing_id=listing_id,
        listed_price=listed_price,
        landed_cost_estimate=landed_cost,
        statistical_price=statistical_price,
        currency=listing.currency,
        source_country=source_country,
        segment=listing_segment.upper() if listing_segment else None,
        listing_quality=listing_quality(listing, evidence),
        included_in_statistics=reason is None,
        excluded_reason=reason,
        observed_at=listing.detected_at,
        description_evidence_count=evidence.description_evidence_count.get(listing_id, 0),
    )


def _mark_duplicates(
    listings: Sequence[Listing], observations: Sequence[MarketObservation]
) -> List[MarketObservation]:
    listings_by_id = {listing.external_id: listing for listing in listings}
    parents = list(range(len(observations)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left_index, left in enumerate(observations):
        left_listing = listings_by_id[left.listing_id]
        for right_index in range(left_index + 1, len(observations)):
            right = observations[right_index]
            if _is_duplicate(left_listing, listings_by_id[right.listing_id]):
                union(left_index, right_index)

    groups: Dict[int, List[MarketObservation]] = {}
    for index, observation in enumerate(observations):
        groups.setdefault(find(index), []).append(observation)
    duplicates = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        winner = min(group, key=lambda item: _duplicate_priority(item))
        duplicates.update(item.listing_id for item in group if item is not winner)
    return [
        replace(
            item,
            included_in_statistics=False,
            excluded_reason=ExclusionReason.DUPLICATE,
        ) if item.listing_id in duplicates else item
        for item in observations
    ]


def _is_duplicate(left: Listing, right: Listing) -> bool:
    if left.url.strip() and left.url.strip().casefold() == right.url.strip().casefold():
        return True
    left_title = " ".join(re.findall(r"[a-z0-9]+", left.title.casefold()))
    right_title = " ".join(re.findall(r"[a-z0-9]+", right.title.casefold()))
    if (
        left_title == right_title
        and left.price == right.price
        and left.source.casefold() == right.source.casefold()
    ):
        return True
    return (
        left.price == right.price
        and left.location.strip().casefold() == right.location.strip().casefold()
        and left.seller.strip().casefold() == right.seller.strip().casefold()
        and abs((left.detected_at - right.detected_at).days) <= 30
    )


def _duplicate_priority(item: MarketObservation) -> Tuple[object, ...]:
    return (
        0 if item.landed_cost_estimate is not None else 1,
        -item.listing_quality,
        -item.description_evidence_count,
        item.observed_at,
        item.listing_id,
    )


def _mark_outliers(
    observations: Sequence[MarketObservation]
) -> List[MarketObservation]:
    eligible = [
        item for item in observations
        if item.included_in_statistics and item.statistical_price is not None
    ]
    fences = iqr_fences([item.statistical_price for item in eligible if item.statistical_price is not None])
    if fences is None:
        return list(observations)
    lower, upper = fences
    outlier_ids = {
        item.listing_id for item in eligible
        if item.statistical_price is not None
        and (item.statistical_price < lower or item.statistical_price > upper)
    }
    return [
        replace(
            item,
            included_in_statistics=False,
            excluded_reason=ExclusionReason.OUTLIER,
        ) if item.listing_id in outlier_ids else item
        for item in observations
    ]


def _clamp(value: int) -> int:
    return max(0, min(100, int(value)))
