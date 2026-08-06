"""Market confidence and compatible historical comparisons."""

from __future__ import annotations

from datetime import timedelta
from typing import List, Optional, Sequence

from .models import ExclusionReason, MarketObservation, MarketSnapshot


def market_confidence(observations: Sequence[MarketObservation]) -> int:
    total = len(observations)
    valid = [item for item in observations if item.included_in_statistics]
    eligible = [
        item for item in observations
        if item.excluded_reason in {None, ExclusionReason.OUTLIER}
    ]
    outliers = [item for item in observations if item.excluded_reason == ExclusionReason.OUTLIER]
    quality_average = (
        sum(item.listing_quality for item in observations) / total if total else 0
    )
    sample_component = 40 * min(len(valid) / 20, 1)
    quality_component = 25 * quality_average / 100
    completeness_component = 15 * len(valid) / total if total else 0
    outlier_component = (
        10 * (1 - len(outliers) / len(eligible)) if eligible else 0
    )
    dated_days = {
        item.observed_at.date() for item in valid if item.observed_at is not None
    }
    temporal_component = 0
    if len(dated_days) >= 21:
        temporal_component = 10
    elif len(dated_days) >= 14:
        temporal_component = 7
    elif len(dated_days) >= 7:
        temporal_component = 4
    elif dated_days:
        temporal_component = 1
    return max(0, min(100, round(
        sample_component + quality_component + completeness_component
        + outlier_component + temporal_component
    )))


def trend(
    current: MarketSnapshot, history: Sequence[MarketSnapshot],
    days: int, tolerance_days: int,
) -> Optional[float]:
    if current.market_confidence < 40 or not _valid_median(current):
        return None
    target = current.created_at - timedelta(days=days)
    compatible = [
        item for item in history
        if _compatible(current, item)
        and item.created_at <= target
        and abs((item.created_at - target).days) <= tolerance_days
        and item.market_confidence >= 40
        and _valid_median(item)
    ]
    if not compatible:
        return None
    previous = min(compatible, key=lambda item: abs(item.created_at - target))
    return (current.median_price / previous.median_price - 1) * 100


def depreciation(
    current: MarketSnapshot, history: Sequence[MarketSnapshot],
    days: int, tolerance_days: int,
) -> Optional[float]:
    if current.market_confidence < 40 or not _valid_median(current):
        return None
    target = current.created_at - timedelta(days=days)
    compatible = [
        item for item in history
        if _compatible(current, item)
        and abs((item.created_at - target).days) <= tolerance_days
        and item.market_confidence >= 40
        and _valid_median(item)
    ]
    if not compatible:
        return None
    previous = min(compatible, key=lambda item: abs(item.created_at - target))
    return (1 - current.median_price / previous.median_price) * 100


def _compatible(current: MarketSnapshot, previous: MarketSnapshot) -> bool:
    return (
        current.product_id == previous.product_id
        and current.segment == previous.segment
        and current.currency.casefold() == previous.currency.casefold()
        and current.target_market_country.casefold()
        == previous.target_market_country.casefold()
    )


def _valid_median(snapshot: MarketSnapshot) -> bool:
    return snapshot.median_price is not None and snapshot.median_price > 0
