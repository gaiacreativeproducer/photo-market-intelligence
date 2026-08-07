"""Canonical product/listing relationship and dashboard workspace assembly."""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Mapping, Optional, Sequence

from catalog import Product, ProductAlias
from knowledge import ProductMatcher
from radar.models import RadarListing

from .listing_analysis import (
    analyze_listings, listing_view, needs_review, requires_structural_review,
)
from .product_associations import ManualProductAssignment
from .view_models import ListingStateView, ProductView, ProductWorkspace


class ProductWorkspaceBuilder:
    """Build every product-facing surface from one listing index."""

    def __init__(
        self, products: Sequence[Product], listings: Sequence[RadarListing],
        aliases: Sequence[ProductAlias] = (),
        assignments: Optional[Mapping[str, ManualProductAssignment]] = None,
    ) -> None:
        self.products = list(products)
        matcher = ProductMatcher(products, aliases) if aliases else None
        self.products_by_id = {item.id: item for item in products}
        self.assignments = dict(assignments or {})
        self._automatic: Dict[str, Dict[str, object]] = {}
        self.listings = []
        for item in listings:
            automatic, metadata = self._automatic_listing(item, matcher)
            self._automatic[item.listing_id] = metadata
            assignment = self.assignments.get(item.listing_id)
            effective = replace(automatic, product_id=assignment.product_id) if assignment else automatic
            self.listings.append(effective)
        self.analysis = analyze_listings(
            products, self.listings, list(self.assignments)
        )
        self._active_by_product: Dict[str, List[RadarListing]] = {}
        for listing in self.listings:
            if listing.active and not self._needs_review(listing):
                self._active_by_product.setdefault(listing.product_id, []).append(listing)
        for values in self._active_by_product.values():
            values.sort(key=lambda item: (item.last_seen_at, item.listing_id), reverse=True)

    def _automatic_listing(
        self,
        listing: RadarListing, matcher: Optional[ProductMatcher]
    ):
        """Derive legacy automatic identity while retaining recognition provenance."""
        result = matcher.recognize(listing.title, listing.description) if matcher else None
        automatic_id = listing.product_id
        if (
            not automatic_id and result is not None and result.product_id
            and result.confidence >= 70 and not result.ambiguous
        ):
            automatic_id = result.product_id
        effective = replace(listing, product_id=automatic_id) if automatic_id else listing
        candidates = []
        if result is not None:
            for candidate in result.candidates[:5]:
                product = self.products_by_id.get(candidate.product_id)
                if product:
                    candidates.append(self._candidate(product, candidate.score))
        product = self.products_by_id.get(automatic_id)
        metadata = {
            "product_id": automatic_id or None,
            "product_name": self._product_name(product),
            "confidence": listing.recognition_confidence,
            "ambiguous": bool(result.ambiguous) if result is not None else not bool(automatic_id),
            "candidates": candidates,
        }
        return effective, metadata

    def active_listings_for_product(self, product_id: str) -> List[RadarListing]:
        """Return the canonical active, accepted offer collection for a product."""
        return list(self._active_by_product.get(product_id, ()))

    def listing_state(self, listing: RadarListing) -> ListingStateView:
        review = self._needs_review(listing)
        product_analysis = self.analysis.get(listing.product_id, {})
        decision = product_analysis.get("decisions", {}).get(listing.listing_id)
        market = product_analysis.get("market", {})
        comparisons = product_analysis.get("comparisons", {})
        has_comparison = any(
            listing.listing_id in (value.get("new_listing_id"), value.get("used_listing_id"))
            for value in comparisons.values()
        )
        has_contradictions = any(
            "contradict" in warning.casefold() for warning in listing.warnings
        )
        lifecycle = "INGESTED"
        if not review:
            lifecycle = "RECOGNIZED"
            if listing.description_confidence >= 0:
                lifecycle = "ANALYZED"
            if decision is not None:
                lifecycle = "EVALUATED"
        return ListingStateView(
            lifecycle, review, bool(market), has_comparison,
            bool(listing.missing_information), has_contradictions, listing.active,
        )

    def listing_views(self) -> List[Dict[str, object]]:
        values = []
        for listing in sorted(
            self.listings, key=lambda item: (item.last_seen_at, item.listing_id), reverse=True
        ):
            view = listing_view(listing, self.products_by_id, self.analysis)
            self._enrich_listing_view(view, listing)
            view["product_url"] = (
                f"/product.html?id={listing.product_id}" if not view["needs_review"] else None
            )
            values.append(view)
        return values

    def build(
        self, product: Product, view: ProductView,
        memory: Mapping[str, object], warnings: Sequence[str],
    ) -> ProductWorkspace:
        listings = self.active_listings_for_product(product.id)
        product_analysis = self.analysis.get(product.id, {})
        offers = []
        for listing in listings:
            offer = listing_view(listing, self.products_by_id, self.analysis)
            self._enrich_listing_view(offer, listing)
            offer["missing_information"] = list(listing.missing_information)
            offer["missing_information_count"] = len(listing.missing_information)
            offer["condition"] = listing.condition or listing.segment
            offers.append(offer)
        lowest_new = self._lowest(offers, "NEW")
        lowest_used = self._lowest(offers, "USED")
        missing = sorted({
            item for listing in listings for item in listing.missing_information
        })
        return ProductWorkspace(
            view, offers, len(offers), lowest_new, lowest_used,
            product_analysis.get("market", {}),
            product_analysis.get("decisions", {}),
            product_analysis.get("comparisons", {}),
            product_analysis.get("default_comparison_key"),
            product_analysis.get("overall_conclusion"), memory,
            list(warnings), missing,
            list(product_analysis.get("comparison_options", [])),
            product_analysis.get("comparison_conclusions", {}),
        )

    def enrich_product(self, view: ProductView, workspace: ProductWorkspace) -> ProductView:
        currencies = {
            item.get("currency") for item in workspace.active_offers if item.get("currency")
        }
        currency = next(iter(currencies)) if len(currencies) == 1 else None
        samples = [
            value for value in workspace.market_snapshots.values()
            if value.get("sample_label")
        ]
        weakest = min(samples, key=lambda value: value.get("valid_sample_size", 0)) if samples else None
        return replace(
            view,
            active_offer_count=workspace.offer_count,
            lowest_new_offer=(workspace.lowest_new_offer or {}).get("price"),
            lowest_used_offer=(workspace.lowest_used_offer or {}).get("price"),
            offer_currency=currency,
            market_sample_label=weakest.get("sample_label") if weakest else None,
        )

    @staticmethod
    def _lowest(
        offers: Sequence[Mapping[str, object]], segment: str
    ) -> Optional[Dict[str, object]]:
        values = [
            item for item in offers
            if item.get("segment") == segment and item.get("price") is not None
        ]
        if not values:
            return None
        return dict(min(values, key=lambda item: (float(item["price"]), str(item["listing_id"]))))

    @staticmethod
    def _state_json(value: ListingStateView) -> Dict[str, object]:
        return {
            "lifecycle": value.lifecycle,
            "needs_product_review": value.needs_product_review,
            "has_market_context": value.has_market_context,
            "has_ownership_comparison": value.has_ownership_comparison,
            "has_missing_information": value.has_missing_information,
            "has_contradictions": value.has_contradictions,
            "is_active": value.is_active,
        }

    def _enrich_listing_view(
        self, view: Dict[str, object], listing: RadarListing
    ) -> None:
        assignment = self.assignments.get(listing.listing_id)
        state = self.listing_state(listing)
        view["state"] = self._state_json(state)
        view["needs_review"] = state.needs_product_review
        view["analysis_status"] = state.lifecycle
        view["automatic_recognition"] = self._automatic[listing.listing_id]
        view["manual_association"] = ({
            "product_id": assignment.product_id,
            "product_name": self._product_name(self.products_by_id.get(assignment.product_id)),
            "assigned_at": assignment.manual_assignment_at.isoformat(),
            "source": assignment.manual_assignment_source,
        } if assignment else None)

    def _needs_review(self, listing: RadarListing) -> bool:
        if listing.listing_id in self.assignments:
            return requires_structural_review(listing)
        return needs_review(listing, self.products_by_id)

    @staticmethod
    def _product_name(product: Optional[Product]) -> Optional[str]:
        if product is None:
            return None
        return " ".join(value for value in (product.brand, product.model, product.version) if value)

    @staticmethod
    def _candidate(product: Product, confidence: int) -> Dict[str, object]:
        return {
            "product_id": product.id,
            "display_name": ProductWorkspaceBuilder._product_name(product),
            "brand": product.brand,
            "model": product.model,
            "version": product.version,
            "category": product.category,
            "mount": product.native_mount,
            "confidence": confidence,
        }
