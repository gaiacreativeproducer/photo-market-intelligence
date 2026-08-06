"""Public models for deterministic ownership comparisons."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from connectors.models import ListingDefect
from market.models import MarketSnapshot


class PurchaseType(str, Enum):
    NEW = "NEW"
    USED = "USED"


class OwnershipRecommendation(str, Enum):
    PREFER_NEW = "PREFER_NEW"
    PREFER_USED = "PREFER_USED"
    EQUIVALENT = "EQUIVALENT"
    NEGOTIATE_USED = "NEGOTIATE_USED"
    WAIT = "WAIT"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class PurchaseOption:
    option_id: str
    purchase_type: PurchaseType
    purchase_price: float
    currency: str
    warranty_months: Optional[int]
    return_window_days: Optional[int]
    estimated_landed_cost: Optional[float]
    shutter_count: Optional[int]
    defects: List[ListingDefect]
    accessories: List[str]
    seller_reliability_score: Optional[float]
    market_snapshot: Optional[MarketSnapshot]
    notes: str
    source_country: Optional[str] = None
    target_market_country: Optional[str] = None
    transferable_warranty: Optional[bool] = None
    invoice_available: Optional[bool] = None
    condition_known: Optional[bool] = None
    contradictory: bool = False
    missing_information: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class OwnershipHorizon:
    months: int
    expected_usage_intensity: str
    planned_resale: bool


@dataclass(frozen=True)
class OwnershipFactor:
    name: str
    category: str
    value: float
    impact: float
    evidence: str
    explanation: str
    confidence: int


@dataclass(frozen=True)
class OwnershipProjection:
    option_id: str
    acquisition_cost: Optional[float]
    risk_cost: float
    estimated_depreciation_percent: Optional[float]
    estimated_resale_value: Optional[float]
    gross_ownership_cost_with_resale: Optional[float]
    gross_ownership_cost_without_resale: Optional[float]
    protection_score: int
    protection_reference_value: float
    liquidity_score: Optional[float]
    confidence: int
    factors: List[OwnershipFactor] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    manual_review: bool = False
    major_risk: bool = False


@dataclass(frozen=True)
class OwnershipComparison:
    recommended_option_id: Optional[str]
    recommendation: OwnershipRecommendation
    confidence: int
    projections: List[OwnershipProjection]
    price_difference: Optional[float]
    expected_cost_difference: Optional[float]
    break_even_discount_percent: Optional[float]
    break_even_target_used_price: Optional[float]
    protection_adjusted_target_range: Optional[Tuple[float, float]]
    factors: List[OwnershipFactor] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
