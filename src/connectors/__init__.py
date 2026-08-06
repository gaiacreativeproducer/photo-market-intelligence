"""Public connector interfaces for Photo Market Intelligence."""

from .base import Connector
from .manager import ConnectorManager
from .mock import MockConnector
from .marketplace_base import ExtractionMode, MarketplaceConnectorBase
from .models import (
    ConnectorError,
    ConnectorHealth,
    ConnectorStatus,
    Listing,
    ManagerResult,
    ProductSearchResult,
    SearchQuery,
)

__all__ = [
    "Connector",
    "ConnectorError",
    "ConnectorHealth",
    "ConnectorManager",
    "ConnectorStatus",
    "Listing",
    "ManagerResult",
    "MockConnector",
    "ProductSearchResult",
    "SearchQuery",
    "ExtractionMode",
    "MarketplaceConnectorBase",
]
