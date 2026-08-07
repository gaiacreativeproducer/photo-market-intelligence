"""Product-scoped eBay Radar refresh service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from catalog import Product, ProductAlias
from connectors.ebay_auth import EbayAuth
from connectors.models import ConnectorError
from radar.importers import load_sources
from radar.models import RadarSource, RadarWatch, SourceType
from radar.persistence import RadarStore
from radar.pipeline import RadarPipeline


class EbayRefreshError(ValueError):
    pass


class EbayRefreshFailure(RuntimeError):
    pass


class EbayRefreshService:
    """Run an explicit, product-scoped eBay refresh from the dashboard.

    Scheduled Radar sources remain configuration-driven. The manual dashboard
    action intentionally has a zero-config fallback: when no enabled eBay
    source is present, it uses a transient EBAY_IT source. Credentials and the
    selected Sandbox/Production environment still come exclusively from the
    process environment through EbayAuth.
    """

    def __init__(self, user_directory: Path, products: Sequence[Product], aliases: Sequence[ProductAlias]) -> None:
        self.user_directory = user_directory
        self.products = list(products)
        self.aliases = list(aliases)

    @property
    def environment(self) -> str:
        return EbayAuth().environment

    def refresh(self, product_id: str):
        product = next((item for item in self.products if item.id == product_id), None)
        if product is None:
            raise KeyError(product_id)

        sources = self._manual_sources()
        now = datetime.now(timezone.utc)
        watch = RadarWatch(
            "ebay-refresh-" + product.id,
            product.id,
            " ".join(value for value in (product.brand, product.model, product.version) if value),
            "EITHER",
            None,
            "",
            [item.source_id for item in sources],
            True,
            "HIGH",
            now,
            now,
        )
        store = RadarStore(self.user_directory)
        before = {item.duplicate_key: item for item in store.load_listings()}
        result = RadarPipeline(
            store, self.products, self.aliases, user_directory=self.user_directory
        ).run(sources, [watch])
        if result.run.status.value == "FAILED":
            raise EbayRefreshFailure(
                result.errors[0].message if result.errors else "eBay refresh failed."
            )
        relevant = [item for item in result.listings if item.run_id == result.run.run_id]
        updated = sum(item.duplicate_key in before for item in relevant)
        return {
            "environment": EbayAuth().environment,
            "source_mode": "CONFIGURED" if self._has_enabled_configured_ebay_source() else "DEFAULT_EBAY_IT",
            "retrieved": result.run.listing_count_raw,
            "recognized": result.recognized_count,
            "persisted_relevant": result.persisted_relevant_count,
            "ignored_accessory_unmatched": result.ignored_accessory_unmatched_count,
            "needs_review": result.needs_review_count,
            "results_retrieved": result.run.listing_count_raw,
            "relevant_offers_added": result.run.listing_count_new,
            "existing_offers_updated": updated,
            "ignored_results": result.run.listing_count_ignored,
            "connector_errors": [item.message for item in result.errors],
            "status": result.run.status.value,
        }

    def _manual_sources(self):
        """Return configured eBay sources or a safe transient EBAY_IT default.

        The dashboard's explicit refresh must not require users to understand
        or create Radar scheduler configuration. If a configured enabled eBay
        source exists, it wins. Otherwise credentials are validated and a
        transient eBay Italy source is used. Nothing is written to disk.
        """
        configured = self._configured_sources()
        enabled = [
            item for item in configured
            if item.enabled and item.source_type == SourceType.EBAY_BROWSE
        ]
        if enabled:
            return enabled

        auth = EbayAuth()
        if not auth.client_id or not auth.client_secret:
            raise EbayRefreshError(
                "eBay non è configurato: imposta PMI_EBAY_CLIENT_ID e "
                "PMI_EBAY_CLIENT_SECRET prima di avviare la dashboard."
            )

        return [RadarSource(
            source_id="ebay-it",
            name="eBay Italia",
            source_type=SourceType.EBAY_BROWSE,
            endpoint="",
            enabled=True,
            country="IT",
            currency="EUR",
            segment="EITHER",
            request_timeout_seconds=15.0,
            retry_count=1,
            minimum_request_interval_seconds=5.0,
            mapping={},
            notes="Transient dashboard source; scheduler configuration not required",
            marketplace_id="EBAY_IT",
            query_limit=50,
        )]

    def _configured_sources(self):
        configuration = self.user_directory / "radar_sources.json"
        return load_sources(configuration) if configuration.is_file() else []

    def _has_enabled_configured_ebay_source(self) -> bool:
        return any(
            item.enabled and item.source_type == SourceType.EBAY_BROWSE
            for item in self._configured_sources()
        )
