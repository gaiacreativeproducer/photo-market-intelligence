"""Shared connector data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ConnectorStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class SearchQuery:
    text: str
    limit: int = 20


@dataclass(frozen=True)
class Listing:
    external_id: str
    source: str
    title: str
    url: str
    price: Optional[float]
    currency: str
    condition: str
    location: str
    seller: str
    description: str
    detected_at: datetime
    raw_data: Dict[str, Any]
    connector_name: str


@dataclass(frozen=True)
class ConnectorHealth:
    connector_name: str
    source_type: str
    status: ConnectorStatus
    checked_at: datetime
    last_success_at: Optional[datetime]
    response_time_ms: int
    result_count: int
    consecutive_failures: int
    message: str


@dataclass
class ConnectorError(Exception):
    error_type: str
    message: str
    severity: str = "error"
    transient: bool = False
    proposed_action: str = "Review connector diagnostics and configuration."

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclass(frozen=True)
class ProductSearchResult:
    connector_name: str
    listings: List[Listing]
    health: ConnectorHealth
    incident_count: int


@dataclass(frozen=True)
class ManagerResult:
    listings: List[Listing] = field(default_factory=list)
    connector_results: List[ProductSearchResult] = field(default_factory=list)
