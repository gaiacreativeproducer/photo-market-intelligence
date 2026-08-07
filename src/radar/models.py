"""Public models for the universal, source-neutral radar pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class SourceType(str, Enum):
    JSON_FEED = "JSON_FEED"
    RSS_ATOM = "RSS_ATOM"
    FILE_IMPORT = "FILE_IMPORT"
    MANUAL_URL = "MANUAL_URL"
    EBAY_BROWSE = "EBAY_BROWSE"


class RunStatus(str, Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    DRY_RUN = "DRY_RUN"


@dataclass(frozen=True)
class RadarSource:
    source_id: str
    name: str
    source_type: SourceType
    endpoint: str
    enabled: bool
    country: str
    currency: str
    segment: str
    request_timeout_seconds: float
    retry_count: int
    minimum_request_interval_seconds: float
    mapping: Dict[str, object]
    notes: str = ""
    marketplace_id: str = ""
    query_limit: int = 50


@dataclass(frozen=True)
class RadarWatch:
    watch_id: str
    product_id: str
    query: str
    condition_preference: str
    max_price: Optional[float]
    currency: str
    source_ids: List[str]
    active: bool
    priority: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RadarListing:
    run_id: str
    listing_id: str
    external_id: str
    source_id: str
    source_name: str
    url: str
    title: str
    description: str
    price: Optional[float]
    currency: str
    source_country: str
    segment: str
    condition: str
    detected_at: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    product_id: str
    recognition_confidence: int
    description_confidence: int
    duplicate_key: str
    active: bool
    raw_record_reference: str
    shutter_count: Optional[int] = None
    warranty_until: Optional[str] = None
    invoice_available: Optional[bool] = None
    original_box_available: Optional[bool] = None
    defects: List[Dict[str, object]] = field(default_factory=list)
    accessories: List[str] = field(default_factory=list)
    seller_claims: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    marketplace_id: str = ""
    original_condition: str = ""
    buying_options: List[str] = field(default_factory=list)
    shipping_cost: Optional[float] = None
    shipping_currency: str = ""
    item_location_country: str = ""
    market_stats_eligible: bool = True


@dataclass(frozen=True)
class RadarRun:
    run_id: str
    started_at: datetime
    finished_at: Optional[datetime]
    status: RunStatus
    source_count: int
    source_success_count: int
    source_failure_count: int
    listing_count_raw: int
    listing_count_normalized: int
    listing_count_new: int
    listing_count_ignored: int
    incident_count: int
    message: str


@dataclass(frozen=True)
class RadarError:
    error_id: str
    run_id: str
    source_id: str
    occurred_at: datetime
    stage: str
    error_type: str
    message: str
    record_reference: str
    recoverable: bool
    resolved: bool = False


@dataclass(frozen=True)
class RadarSourceHealth:
    source_id: str
    status: str
    checked_at: datetime
    last_success_at: Optional[datetime]
    response_time_ms: int
    raw_record_count: int
    normalized_record_count: int
    relevant_persisted_count: int
    consecutive_failures: int
    message: str


@dataclass(frozen=True)
class ImportedRecord:
    values: Dict[str, object]
    reference: str
    explicitly_supplied: bool = False


@dataclass(frozen=True)
class SourceBatch:
    records: List[ImportedRecord]
    errors: List[str] = field(default_factory=list)
