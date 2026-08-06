"""Deterministic connector used until live integrations are introduced."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from .base import Connector
from .models import ConnectorError, Listing, SearchQuery


class MockConnector(Connector):
    SCENARIOS = {
        "healthy",
        "empty",
        "timeout",
        "timeout_then_success",
        "authentication_failure",
        "malformed",
        "partial",
    }

    def __init__(self, scenario: str = "healthy", **kwargs) -> None:
        if scenario not in self.SCENARIOS:
            raise ValueError(f"unknown mock scenario: {scenario}")
        super().__init__(
            name=kwargs.pop("name", "mock-marketplace"),
            source_type=kwargs.pop("source_type", "mock"),
            **kwargs,
        )
        self.scenario = scenario
        self.search_attempts = 0

    def search(self, query: SearchQuery) -> List[Listing]:
        self.search_attempts += 1
        if self.scenario == "timeout":
            raise TimeoutError("mock connector timed out")
        if self.scenario == "timeout_then_success" and self.search_attempts == 1:
            raise TimeoutError("mock connector timed out temporarily")
        if self.scenario == "authentication_failure":
            raise ConnectorError(
                "authentication",
                "mock credentials were rejected",
                proposed_action="Check connector credentials and permissions.",
            )
        if self.scenario == "malformed":
            return [{"unexpected": "payload"}]  # type: ignore[list-item]
        if self.scenario == "empty":
            return []

        listing = self._listing_for(query)
        if self.scenario == "partial":
            listing = Listing(
                external_id=listing.external_id,
                source=listing.source,
                title=listing.title,
                url=listing.url,
                price=listing.price,
                currency=listing.currency,
                condition=listing.condition,
                location="",
                seller="",
                description="",
                detected_at=listing.detected_at,
                raw_data=listing.raw_data,
                connector_name=listing.connector_name,
            )
        return [listing]

    def _listing_for(self, query: SearchQuery) -> Listing:
        normalized = query.text.casefold()
        if "24-70" in normalized and "sigma" in normalized:
            values = (
                "sigma-24-70-ii-001",
                "Sigma 24-70mm f/2.8 DG DN II Art Sony E",
                1049.0,
                "Used - Excellent",
                "Milano",
                "Photo Pro Milano",
                "Boxed lens with caps and hood.",
            )
        elif "vintage" in normalized or "helios" in normalized:
            values = (
                "helios-44-2-001",
                "Helios 44-2 58mm f/2 M42 vintage lens",
                65.0,
                "Used - Good",
                "Roma",
                "Vintage Optics",
                "Manual-focus M42 lens with normal cosmetic wear.",
            )
        else:
            values = (
                "sony-a7iv-001",
                "Sony Alpha A7 IV body",
                1649.0,
                "Used - Excellent",
                "Torino",
                "Camera Market",
                "Full-frame body with battery and original box.",
            )
        external_id, title, price, condition, location, seller, description = values
        return Listing(
            external_id=external_id,
            source="Mock Marketplace",
            title=title,
            url=f"https://example.invalid/listings/{external_id}",
            price=price,
            currency="EUR",
            condition=condition,
            location=location,
            seller=seller,
            description=description,
            detected_at=datetime.now(timezone.utc),
            raw_data={"mock": True, "query": query.text},
            connector_name=self.name,
        )
