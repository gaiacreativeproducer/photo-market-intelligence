"""Data models returned and consumed by the decision engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Recommendation(str, Enum):
    BUY_USED = "BUY_USED"
    BUY_NEW = "BUY_NEW"
    NEGOTIATE = "NEGOTIATE"
    MONITOR = "MONITOR"
    PASS = "PASS"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class MarketStatistics:
    median_used_price: Optional[float]
    lowest_recent_used_price: Optional[float]
    median_new_price: Optional[float]
    sample_size: int
    price_trend_percent: Optional[float]
    observation_window_days: int
    currency: Optional[str]
    replacement_model_released: Optional[bool] = None


@dataclass(frozen=True)
class NewAlternative:
    price: float
    currency: str
    warranty_months: int
    return_window_days: int
    seller_reliability_score: float
    notes: str


@dataclass(frozen=True)
class DecisionFactor:
    name: str
    category: str
    score_impact: int
    evidence: str
    explanation: str
    confidence: int


@dataclass(frozen=True)
class DecisionReport:
    buy_score: int
    confidence: int
    recommendation: Recommendation
    expected_fair_price: Optional[float]
    ownership_cost_score: Optional[int]
    resale_score: Optional[int]
    risk_score: int
    wait_probability: Optional[int]
    new_vs_used_recommendation: Recommendation
    estimated_used_advantage: Optional[float]
    factors: List[DecisionFactor] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
