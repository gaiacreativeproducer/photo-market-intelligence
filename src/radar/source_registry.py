"""Explicit registry for radar source adapters and future marketplaces."""

from __future__ import annotations

from typing import Dict, Type


class SourceRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[str, Type] = {}

    def register(self, source_type: str, adapter: Type) -> None:
        key = source_type.upper()
        if key in self._adapters:
            raise ValueError(f"source type already registered: {key}")
        self._adapters[key] = adapter

    def adapter(self, source_type: str):
        try:
            return self._adapters[source_type.upper()]
        except KeyError:
            raise ValueError(f"unregistered source type: {source_type}")

    @property
    def source_types(self):
        return tuple(sorted(self._adapters))


def default_registry() -> SourceRegistry:
    from connectors.file_import import FileImportConnector
    from connectors.json_feed import JsonFeedConnector
    from connectors.manual_url import ManualUrlConnector
    from connectors.rss_feed import RssFeedConnector
    registry = SourceRegistry()
    registry.register("JSON_FEED", JsonFeedConnector)
    registry.register("RSS_ATOM", RssFeedConnector)
    registry.register("FILE_IMPORT", FileImportConnector)
    registry.register("MANUAL_URL", ManualUrlConnector)
    return registry
