"""Privacy allowlists for dashboard JSON responses."""

from __future__ import annotations

from typing import Dict

from .view_models import ProductView, ProductWorkspace


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
        "active_offer_count": product.active_offer_count,
        "lowest_new_offer": product.lowest_new_offer,
        "lowest_used_offer": product.lowest_used_offer,
        "offer_currency": product.offer_currency,
        "market_sample_label": product.market_sample_label,
        "placeholder_category": product.category.casefold().replace(" ", "-"),
    }


def workspace_json(workspace: ProductWorkspace) -> Dict[str, object]:
    return {
        "product": product_json(workspace.product),
        "active_offers": workspace.active_offers,
        "offer_count": workspace.offer_count,
        "lowest_new_offer": workspace.lowest_new_offer,
        "lowest_used_offer": workspace.lowest_used_offer,
        "market_snapshots": workspace.market_snapshots,
        "listing_analyses": workspace.listing_analyses,
        "available_comparisons": workspace.available_comparisons,
        "selected_comparison": workspace.selected_comparison,
        "overall_conclusion": workspace.overall_conclusion,
        "memory_context": workspace.memory_context,
        "warnings": workspace.warnings,
        "missing_information": workspace.missing_information,
        "comparison_options": workspace.comparison_options,
        "comparison_conclusions": workspace.comparison_conclusions,
    }


def detail_json(detail: Dict[str, object]) -> Dict[str, object]:
    value = {
        "product": product_json(detail["product"]),
        "aliases": list(detail["aliases"]), "market": detail["market"],
        "new_vs_used": detail["new_vs_used"], "listings": detail["listings"],
        "ownership": detail["ownership"], "memory": detail["memory"],
        "listing_market": detail.get("listing_market", {}),
        "listing_decisions": detail.get("listing_decisions", {}),
        "ownership_comparisons": detail.get("ownership_comparisons", {}),
        "default_comparison_key": detail.get("default_comparison_key"),
        "comparison_options": detail.get("comparison_options", []),
        "overall_conclusion": detail.get("overall_conclusion"),
        "comparison_conclusions": detail.get("comparison_conclusions", {}),
        "warnings": detail["warnings"],
    }
    workspace = detail.get("workspace")
    if workspace is not None:
        value["workspace"] = workspace_json(workspace)
    return value
