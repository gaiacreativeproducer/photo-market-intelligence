"""Typed notification state and strict user preferences."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


class NotificationType(str, Enum):
    NEW_MATCH = "NEW_MATCH"
    PRICE_BELOW_TARGET = "PRICE_BELOW_TARGET"
    HIGH_CONFIDENCE_MATCH = "HIGH_CONFIDENCE_MATCH"
    CONNECTOR_FAILED = "CONNECTOR_FAILED"
    CONNECTOR_RECOVERED = "CONNECTOR_RECOVERED"
    RADAR_PARTIAL = "RADAR_PARTIAL"
    RADAR_FAILED = "RADAR_FAILED"
    MARKET_CHANGE = "MARKET_CHANGE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    SYSTEM = "SYSTEM"


class Severity(str, Enum):
    INFO = "INFO"
    NOTICE = "NOTICE"
    IMPORTANT = "IMPORTANT"
    CRITICAL = "CRITICAL"


class DigestMode(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    DISABLED = "DISABLED"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class Notification:
    notification_id: str
    notification_type: NotificationType
    severity: Severity
    title: str
    message: str
    product_id: str
    listing_id: str
    source_id: str
    created_at: datetime
    read: bool
    dismissed: bool
    action_url: str
    evidence: Dict[str, object]
    deduplication_key: str
    delivery_status: DeliveryStatus = DeliveryStatus.NOT_APPLICABLE
    delivered_at: Optional[datetime] = None
    delivery_attempts: int = 0
    delivery_message: str = "dashboard notification is immediately available"


@dataclass(frozen=True)
class NotificationPreference:
    enabled: bool = True
    minimum_severity: Severity = Severity.NOTICE
    minimum_recognition_confidence: int = 75
    maximum_price: Optional[float] = None
    maximum_price_currency: Optional[str] = None
    active_wishlist_only: bool = True
    notify_new_listing: bool = True
    notify_price_below_target: bool = True
    notify_high_confidence_match: bool = False
    notify_connector_failure: bool = True
    notify_connector_recovery: bool = True
    notify_market_change: bool = False
    notify_manual_review: bool = True
    digest_mode: DigestMode = DigestMode.IMMEDIATE
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    assistant_history_enabled: bool = False
