"""Base contract implemented by marketplace connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from .models import ConnectorHealth, Listing, SearchQuery


class Connector(ABC):
    def __init__(
        self,
        name: str,
        source_type: str,
        enabled: bool = True,
        timeout_seconds: float = 10.0,
        retry_count: int = 2,
    ) -> None:
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")
        if retry_count < 0:
            raise ValueError("retry_count cannot be negative")
        self.name = name
        self.source_type = source_type
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count

    @abstractmethod
    def search(self, query: SearchQuery) -> List[Listing]:
        """Return normalized listings or raise a structured operational error."""

    def health_check(self) -> Optional[ConnectorHealth]:
        """Optionally perform a lightweight check without duplicating a search."""
        return None
