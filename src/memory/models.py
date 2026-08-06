"""Public, privacy-safe models for deterministic user memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional


class WishlistPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class WishlistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    PURCHASED = "PURCHASED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class PurchaseCondition(str, Enum):
    NEW = "NEW"
    USED = "USED"
    EITHER = "EITHER"


class RiskTolerance(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class WishlistFlag(str, Enum):
    ALREADY_OWNED = "ALREADY_OWNED"
    CONDITION_CONFLICT = "CONDITION_CONFLICT"
    CURRENCY_CONFLICT = "CURRENCY_CONFLICT"
    TARGET_DATE_PASSED = "TARGET_DATE_PASSED"
    POSSIBLE_REDUNDANCY = "POSSIBLE_REDUNDANCY"
    COMPLEMENTS_INVENTORY = "COMPLEMENTS_INVENTORY"
    DUPLICATE_PRODUCT = "DUPLICATE_PRODUCT"
    TARGET_PRICE_MISSING = "TARGET_PRICE_MISSING"
    NONE = "NONE"


@dataclass(frozen=True)
class OwnedItem:
    item_id: str
    product_id: str
    purchase_date: Optional[date]
    purchase_price: Optional[float]
    currency: Optional[str]
    condition_at_purchase: Optional[PurchaseCondition]
    shutter_count_at_purchase: Optional[int]
    current_shutter_count: Optional[int]
    warranty_until: Optional[date]
    accessories: List[str]
    serial_reference: Optional[str]
    notes: str
    active: bool


@dataclass(frozen=True)
class WishlistItem:
    wishlist_id: str
    product_id: str
    target_price: Optional[float]
    currency: Optional[str]
    priority: WishlistPriority
    purchase_condition_preference: PurchaseCondition
    target_date: Optional[date]
    reason: str
    status: WishlistStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DecisionHistoryEntry:
    entry_id: str
    product_id: str
    listing_url: str
    source: str
    decision: str
    decision_score: Optional[int]
    ownership_recommendation: str
    observed_price: Optional[float]
    currency: Optional[str]
    reasons: List[str]
    rejected_reason: str
    created_at: datetime


@dataclass(frozen=True)
class UserPreferences:
    target_market_country: str = ""
    preferred_currency: str = "EUR"
    default_purchase_condition: PurchaseCondition = PurchaseCondition.EITHER
    risk_tolerance: RiskTolerance = RiskTolerance.MEDIUM
    warranty_importance: int = 50
    resale_importance: int = 50
    weight_sensitivity: int = 50
    brand_preferences: List[str] = field(default_factory=list)
    excluded_brands: List[str] = field(default_factory=list)
    preferred_sources: List[str] = field(default_factory=list)
    excluded_sources: List[str] = field(default_factory=list)
    notification_threshold: int = 80
    notes: str = ""


@dataclass(frozen=True)
class InventoryCoverage:
    camera_bodies: List[str]
    primes: List[str]
    zooms: List[str]
    cinema_lenses: List[str]
    accessories: List[str]
    duplicate_products: Dict[str, int]
    product_families: List[str]
    focal_categories: Dict[str, List[str]]
    unknown_focal_products: List[str]


@dataclass(frozen=True)
class WishlistContext:
    wishlist_id: str
    product_id: str
    flags: List[WishlistFlag]
    reasons: List[str]


@dataclass(frozen=True)
class UserContext:
    owned_product_ids: List[str]
    active_wishlist: List[WishlistItem]
    recent_decisions: List[DecisionHistoryEntry]
    preferences: UserPreferences
    inventory_coverage: InventoryCoverage
    wishlist_context: List[WishlistContext]
    missing_system_gaps: List[str]
