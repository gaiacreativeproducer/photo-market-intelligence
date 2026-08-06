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


@dataclass(frozen=True)
class DashboardData:
    mode: str
    products: List[ProductView]
    details: Mapping[str, Dict[str, object]]
    context: Dict[str, object]


class DashboardDataProvider(Protocol):
    def load(self) -> DashboardData:
        ...
