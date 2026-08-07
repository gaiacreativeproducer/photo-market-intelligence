"""Product-scoped eBay Radar refresh service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from catalog import Product, ProductAlias
from connectors.ebay_auth import EbayAuth
from radar.importers import load_sources
from radar.models import RadarWatch, SourceType
from radar.persistence import RadarStore
from radar.pipeline import RadarPipeline


class EbayRefreshError(ValueError):
    pass


class EbayRefreshFailure(RuntimeError):
    pass


class EbayRefreshService:
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
        configuration = self.user_directory / "radar_sources.json"
        configured_sources = load_sources(configuration) if configuration.is_file() else []
        sources = [
            item for item in configured_sources
            if item.enabled and item.source_type == SourceType.EBAY_BROWSE
        ]
        if not sources:
            raise EbayRefreshError("No enabled eBay Browse sources are configured.")
        now = datetime.now(timezone.utc)
        watch = RadarWatch(
            "ebay-refresh-" + product.id, product.id,
            " ".join(value for value in (product.brand, product.model, product.version) if value),
            "EITHER", None, "", [item.source_id for item in sources], True, "HIGH", now, now,
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
