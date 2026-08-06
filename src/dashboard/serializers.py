"""Privacy allowlists for dashboard JSON responses."""

from __future__ import annotations

from typing import Dict

from .view_models import ProductView


def product_json(product: ProductView) -> Dict[str, object]:
    return {
        "id": product.id, "display_name": product.display_name,
        "brand": product.brand, "model": product.model, "version": product.version,
        "category": product.category, "product_type": product.product_type,
        "native_mount": product.native_mount, "release_year": product.release_year,
        "owned": product.owned, "wishlist": product.wishlist,
        "wishlist_priority": product.wishlist_priority,
        "target_price": product.target_price, "target_currency": product.target_currency,
        "new_median": product.new_median, "used_median": product.used_median,
        "market_currency": product.market_currency,
        "market_confidence": product.market_confidence,
        "latest_recommendation": product.latest_recommendation,
        "warning_count": product.warning_count,
        "placeholder_category": product.category.casefold().replace(" ", "-"),
    }


def detail_json(detail: Dict[str, object]) -> Dict[str, object]:
    return {
        "product": product_json(detail["product"]),
        "aliases": list(detail["aliases"]), "market": detail["market"],
        "new_vs_used": detail["new_vs_used"], "listings": detail["listings"],
        "ownership": detail["ownership"], "memory": detail["memory"],
        "listing_market": detail.get("listing_market", {}),
        "listing_decisions": detail.get("listing_decisions", {}),
        "ownership_comparisons": detail.get("ownership_comparisons", {}),
        "default_comparison_key": detail.get("default_comparison_key"),
        "comparison_options": detail.get("comparison_options", []),
        "warnings": detail["warnings"],
    }
