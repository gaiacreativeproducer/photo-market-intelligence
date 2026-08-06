"""Bounded, non-recommendation context assembled from structured user state."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from catalog import Product

from .inventory import summarize_inventory
from .models import DecisionHistoryEntry, OwnedItem, UserContext, UserPreferences, WishlistItem, WishlistStatus
from .wishlist import wishlist_contexts


def build_user_context(
    inventory: Sequence[OwnedItem], wishlist: Sequence[WishlistItem],
    decisions: Sequence[DecisionHistoryEntry], preferences: UserPreferences,
    products: Sequence[Product], as_of: date, recent_decision_limit: int = 20,
) -> UserContext:
    if recent_decision_limit < 0:
        raise ValueError("recent_decision_limit must not be negative")
    active_inventory = [item for item in inventory if item.active]
    active_wishlist = [item for item in wishlist if item.status == WishlistStatus.ACTIVE]
    recent = sorted(decisions, key=lambda item: (item.created_at, item.entry_id), reverse=True)[:recent_decision_limit]
    coverage = summarize_inventory(inventory, products)
    contexts = wishlist_contexts(wishlist, inventory, products, preferences, as_of)
    gaps = []
    if not preferences.target_market_country:
        gaps.append("target market missing")
    if not coverage.zooms or not coverage.focal_categories["STANDARD"]:
        gaps.append("no standard zoom owned")
    if coverage.duplicate_products:
        gaps.append("duplicate products owned")
    if any(any(flag.value == "ALREADY_OWNED" for flag in context.flags) for context in contexts):
        gaps.append("wishlist product already owned")
    return UserContext(
        [item.product_id for item in active_inventory], active_wishlist, recent,
        preferences, coverage, contexts, gaps,
    )
