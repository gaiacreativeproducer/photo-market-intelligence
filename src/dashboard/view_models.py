"""Explicit dashboard view models and provider boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Protocol


@dataclass(frozen=True)
class ProductView:
    id: str
    display_name: str
    brand: str
    model: str
    version: str
    category: str
    product_type: str
    native_mount: str
    release_year: Optional[int]
    aliases: List[str] = field(default_factory=list)
    owned: bool = False
    wishlist: bool = False
    wishlist_priority: Optional[str] = None
    target_price: Optional[float] = None
    target_currency: Optional[str] = None
    new_median: Optional[float] = None
    used_median: Optional[float] = None
    market_currency: Optional[str] = None
    market_confidence: Optional[int] = None
    latest_recommendation: Optional[str] = None
    warning_count: int = 0
    active_offer_count: int = 0
    lowest_new_offer: Optional[float] = None
    lowest_used_offer: Optional[float] = None
    offer_currency: Optional[str] = None
    market_sample_label: Optional[str] = None


@dataclass(frozen=True)
class ListingStateView:
    lifecycle: str
    needs_product_review: bool
    has_market_context: bool
    has_ownership_comparison: bool
    has_missing_information: bool
    has_contradictions: bool
    is_active: bool


@dataclass(frozen=True)
class ProductWorkspace:
    product: ProductView
    active_offers: List[Dict[str, object]]
    offer_count: int
    lowest_new_offer: Optional[Dict[str, object]]
    lowest_used_offer: Optional[Dict[str, object]]
    market_snapshots: Mapping[str, object]
    listing_analyses: Mapping[str, object]
    available_comparisons: Mapping[str, object]
    selected_comparison: Optional[str]
    overall_conclusion: Optional[Mapping[str, object]]
    memory_context: Mapping[str, object]
    warnings: List[str]
    missing_information: List[str]
    comparison_options: List[Dict[str, object]] = field(default_factory=list)
    comparison_conclusions: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DashboardData:
    mode: str
    products: List[ProductView]
    details: Mapping[str, Dict[str, object]]
    context: Dict[str, object]


class DashboardDataProvider(Protocol):
    def load(self) -> DashboardData:
        ...
