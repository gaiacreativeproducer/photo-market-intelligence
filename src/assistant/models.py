"""Public contextual-assistant request and response models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class AssistantIntent(str, Enum):
    PRODUCT_OVERVIEW = "PRODUCT_OVERVIEW"
    MARKET_SUMMARY = "MARKET_SUMMARY"
    NEW_VS_USED = "NEW_VS_USED"
    EXPLAIN_RECOMMENDATION = "EXPLAIN_RECOMMENDATION"
    EXPLAIN_WARNING = "EXPLAIN_WARNING"
    COMPARE_PRODUCTS = "COMPARE_PRODUCTS"
    WISHLIST_STATUS = "WISHLIST_STATUS"
    INVENTORY_STATUS = "INVENTORY_STATUS"
    LISTING_SUMMARY = "LISTING_SUMMARY"
    SYSTEM_STATUS = "SYSTEM_STATUS"
    HELP = "HELP"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class AssistantRequest:
    message: str
    product_id: Optional[str]
    comparison_product_ids: List[str]
    listing_id: Optional[str]
    page_context: str
    created_at: datetime


@dataclass(frozen=True)
class AssistantFact:
    label: str
    value: str
    source_module: str
    confidence: int


@dataclass(frozen=True)
class AssistantResponse:
    answer: str
    intent: AssistantIntent
    confidence: int
    facts: List[AssistantFact] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggested_actions: List[str] = field(default_factory=list)
    related_product_ids: List[str] = field(default_factory=list)
    source_sections: List[str] = field(default_factory=list)
