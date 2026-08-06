"""Metadata-only contract for future dedicated marketplace connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class ExtractionMode(str, Enum):
    OFFICIAL_API = "OFFICIAL_API"
    PUBLIC_FEED = "PUBLIC_FEED"
    USER_EXPORT = "USER_EXPORT"
    DEDICATED_HTML_CONNECTOR = "DEDICATED_HTML_CONNECTOR"


class MarketplaceConnectorBase(ABC):
    marketplace_name: str
    connector_version: str
    supported_countries: tuple
    supported_segments: tuple
    extraction_mode: ExtractionMode
    terms_review_required: bool

    @abstractmethod
    def fetch_records(self): ...
    @abstractmethod
    def normalize_record(self, record): ...
    @abstractmethod
    def validate_source_configuration(self): ...
    @abstractmethod
    def health_check(self): ...
