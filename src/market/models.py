"""Public models for deterministic market intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class ExclusionReason(str, Enum):
    OUTLIER = "OUTLIER"
    MISSING_PRICE = "MISSING_PRICE"
    WRONG_CURRENCY = "WRONG_CURRENCY"
    PRODUCT_NOT_CONFIRMED = "PRODUCT_NOT_CONFIRMED"
    SEVERE_DAMAGE = "SEVERE_DAMAGE"
    DUPLICATE = "DUPLICATE"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    SEGMENT_MISMATCH = "SEGMENT_MISMATCH"
    LANDED_COST_UNKNOWN = "LANDED_COST_UNKNOWN"
    UNSUPPORTED_BUYING_OPTION = "UNSUPPORTED_BUYING_OPTION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MarketObservation:
    listing_id: str
    listed_price: Optional[float]
    landed_cost_estimate: Optional[float]
    statistical_price: Optional[float]
    currency: str
    source_country: Optional[str]
    segment: Optional[str]
    listing_quality: int
    included_in_statistics: bool
    excluded_reason: Optional[ExclusionReason]
    observed_at: Optional[datetime] = None
    description_evidence_count: int = 0


@dataclass(frozen=True)
class MarketSnapshot:
    product_id: str
    target_market_country: str
    source_countries: List[str]
    currency: str
    segment: str
    created_at: datetime
    sample_size: int
    valid_sample_size: int
    outlier_count: int
    median_price: Optional[float]
    mean_price: Optional[float]
    trimmed_mean: Optional[float]
    lowest_price: Optional[float]
    highest_price: Optional[float]
    standard_deviation: Optional[float]
    percentile_10: Optional[float]
    percentile_25: Optional[float]
    percentile_75: Optional[float]
    percentile_90: Optional[float]
    price_volatility: Optional[float]
    market_confidence: int
    trend_30d: Optional[float]
    trend_90d: Optional[float]
    trend_180d: Optional[float]
    estimated_12_month_depreciation: Optional[float]
    estimated_24_month_depreciation: Optional[float]
    listing_quality_average: float
    observations: List[MarketObservation] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
