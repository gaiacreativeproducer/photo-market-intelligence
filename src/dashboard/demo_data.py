"""Local and demo dashboard providers; demo fixtures only enrich the catalog."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from catalog import Product, ProductAlias, load_product_aliases, load_products
from memory import (
    DecisionHistoryEntry, OwnedItem, PurchaseCondition, UserPreferences,
    WishlistItem, WishlistPriority, WishlistStatus, build_user_context,
    load_decision_history, load_inventory, load_preferences, load_wishlist,
)
from decision.models import DecisionReport, Recommendation
from market.models import MarketSnapshot
from ownership.models import (
    OwnershipComparison, OwnershipProjection, OwnershipRecommendation,
)
from radar.persistence import RadarStore
from .product_workspace import ProductWorkspaceBuilder

from .view_models import DashboardData, ProductView


ENRICHED_IDS = {
    "sony-alpha-a7-iv", "sony-alpha-a7-v", "panasonic-lumix-s5-ii",
    "sigma-24-70mm-f2-8-dg-dn-art",
    "sigma-24-70mm-f2-8-dg-dn-ii-art", "sony-fe-50mm-f1-4-gm",
    "sony-fe-70-200mm-f2-8-gm-oss-ii",
}


class LocalDashboardDataProvider:
    def __init__(self, project_root: Path, user_directory: Optional[Path] = None) -> None:
        self.project_root = project_root
        self.user_directory = user_directory or project_root / "data" / "user"

    def load(self) -> DashboardData:
        products, aliases = _catalog(self.project_root)
        inventory: List[OwnedItem] = []
        wishlist: List[WishlistItem] = []
        decisions: List[DecisionHistoryEntry] = []
        preferences = UserPreferences()
        paths = self.user_directory
        try:
            if (paths / "user_inventory.csv").is_file():
                inventory = load_inventory(paths / "user_inventory.csv", products)
            if (paths / "user_wishlist.csv").is_file():
                wishlist = load_wishlist(paths / "user_wishlist.csv", products)
            if (paths / "user_decision_history.csv").is_file():
                decisions = load_decision_history(paths / "user_decision_history.csv", products)
            if (paths / "user_preferences.json").is_file():
                preferences = load_preferences(paths / "user_preferences.json")
        except (OSError, ValueError):
            raise
        data = _assemble("LOCAL", products, aliases, inventory, wishlist, decisions, preferences, False)
        return _add_radar_data(data, RadarStore(paths), products, aliases)


class DemoDashboardDataProvider(LocalDashboardDataProvider):
    def load(self) -> DashboardData:
        products, aliases = _catalog(self.project_root)
        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        inventory = [
            OwnedItem("demo-body", "sony-alpha-a7-iv", date(2024, 1, 1), 1500, "EUR", PurchaseCondition.NEW, 0, 20000, None, [], "BODY-A", "private", True),
            OwnedItem("demo-prime", "sony-fe-50mm-f1-4-gm", date(2025, 1, 1), 900, "EUR", PurchaseCondition.USED, None, None, None, [], None, "private", True),
        ]
        wishlist = [
            WishlistItem("demo-standard", "sigma-24-70mm-f2-8-dg-dn-ii-art", 950, "EUR", WishlistPriority.HIGH, PurchaseCondition.EITHER, None, "", WishlistStatus.ACTIVE, now, now),
            WishlistItem("demo-tele", "sony-fe-70-200mm-f2-8-gm-oss-ii", 1800, "EUR", WishlistPriority.MEDIUM, PurchaseCondition.USED, None, "", WishlistStatus.ACTIVE, now, now),
        ]
        decisions = [DecisionHistoryEntry("demo-decision", "sony-alpha-a7-iv", "https://example.invalid/listing/a7iv", "Demo Market", "BUY_USED", 88, "PREFER_USED", 1200, "EUR", ["Below used median"], "", now)]
        data = _assemble("DEMO", products, aliases, inventory, wishlist, decisions, UserPreferences(target_market_country="Italy"), True)
        return _add_radar_data(data, RadarStore(self.user_directory), products, aliases)


def _catalog(root: Path):
    products = load_products(root / "data" / "products.csv")
    aliases = load_product_aliases(root / "data" / "product_aliases.csv", products)
    return products, aliases


def _assemble(
    mode: str, products: Sequence[Product], aliases: Sequence[ProductAlias],
    inventory: Sequence[OwnedItem], wishlist: Sequence[WishlistItem],
    decisions: Sequence[DecisionHistoryEntry], preferences: UserPreferences,
    enrich: bool,
) -> DashboardData:
    aliases_by_id: Dict[str, List[str]] = {}
    for alias in aliases:
        aliases_by_id.setdefault(alias.product_id, []).append(alias.alias)
    owned = {item.product_id for item in inventory if item.active}
    active_wishlist = {item.product_id: item for item in wishlist if item.status == WishlistStatus.ACTIVE}
    latest = {}
    for entry in sorted(decisions, key=lambda item: item.created_at):
        latest[entry.product_id] = entry
    views = []
    details: Dict[str, Dict[str, object]] = {}
    for index, product in enumerate(products):
        rich = enrich and product.id in ENRICHED_IDS
        new_median = float(1400 + index * 25) if rich else None
        used_median = float(1000 + index * 20) if rich else None
        wish = active_wishlist.get(product.id)
        decision = latest.get(product.id)
        view = ProductView(
            product.id, " ".join(part for part in (product.brand, product.model, product.version) if part),
            product.brand, product.model, product.version, product.category,
            product.product_type, product.native_mount, product.release_year,
            sorted(aliases_by_id.get(product.id, [])), product.id in owned,
            wish is not None, wish.priority.value if wish else None,
            wish.target_price if wish else None, wish.currency if wish else None,
            new_median, used_median, "EUR" if rich else None, 80 if rich else None,
            decision.decision if decision else ("MONITOR" if rich else None),
            0 if rich else 1,
        )
        views.append(view)
        details[product.id] = _detail(view, rich, inventory, wishlist, decisions)
    context = build_user_context(inventory, wishlist, decisions, preferences, products, date(2026, 8, 1))
    safe_context = {
        "owned_product_ids": context.owned_product_ids,
        "active_wishlist_count": len(context.active_wishlist),
        "recent_decision_count": len(context.recent_decisions),
        "wishlist_context": [{"product_id": item.product_id, "flags": [flag.value for flag in item.flags]} for item in context.wishlist_context],
        "inventory_gaps": context.missing_system_gaps,
        "wishlist_items": [_wishlist_view(item, products, context.wishlist_context) for item in active_wishlist.values()],
        "inventory_items": [_inventory_view(item, products) for item in inventory],
        "decision_items": [_decision_view(item, products) for item in sorted(decisions,key=lambda value:(value.created_at,value.entry_id),reverse=True)],
    }
    return DashboardData(mode, sorted(views, key=lambda item: item.id), details, safe_context)


def _name(product_id,products):
    product=next((item for item in products if item.id==product_id),None)
    return " ".join(value for value in (product.brand,product.model,product.version) if value) if product else product_id


def _wishlist_view(item,products,contexts):
    context=next((value for value in contexts if value.wishlist_id==item.wishlist_id),None)
    return {"wishlist_id":item.wishlist_id,"product_id":item.product_id,"product_name":_name(item.product_id,products),
        "priority":item.priority.value,"preferred_condition":item.purchase_condition_preference.value,
        "target_price":item.target_price,"currency":item.currency,"target_date":item.target_date.isoformat() if item.target_date else None,
        "flags":[flag.value for flag in context.flags] if context else [],"status":item.status.value,
        "product_url":f"/product.html?id={item.product_id}"}


def _inventory_view(item,products):
    return {"item_id":item.item_id,"product_id":item.product_id,"product_name":_name(item.product_id,products),
        "purchase_date":item.purchase_date.isoformat() if item.purchase_date else None,"purchase_price":item.purchase_price,
        "currency":item.currency,"condition_at_purchase":item.condition_at_purchase.value if item.condition_at_purchase else None,
        "current_shutter_count":item.current_shutter_count,"warranty_until":item.warranty_until.isoformat() if item.warranty_until else None,
        "active":item.active,"accessories":list(item.accessories),"product_url":f"/product.html?id={item.product_id}"}


def _decision_view(item,products):
    return {"entry_id":item.entry_id,"product_id":item.product_id,"product_name":_name(item.product_id,products),
        "source":item.source,"observed_price":item.observed_price,"currency":item.currency,"decision":item.decision,
        "ownership_recommendation":item.ownership_recommendation,"reasons":list(item.reasons[:3]),
        "created_at":item.created_at.isoformat(),"listing_url":item.listing_url if item.listing_url.startswith(("http://","https://")) else None,
        "product_url":f"/product.html?id={item.product_id}"}


def _detail(view: ProductView, rich: bool, inventory, wishlist, decisions) -> Dict[str, object]:
    market = None
    ownership = None
    new_vs_used = None
    listings: List[Dict[str, object]] = []
    if rich:
        used_snapshot = _snapshot(view.id, "USED", view.used_median)
        new_snapshot = _snapshot(view.id, "NEW", view.new_median)
        decision = DecisionReport(
            82, 84, Recommendation.BUY_USED, view.used_median, 75, 70, 15,
            20, Recommendation.BUY_USED, 180.0, [],
            ["Structured demo decision"], [], [],
        )
        projection = OwnershipProjection(
            "demo-used", view.used_median, 20.0, 10.0, 800.0, 220.0,
            (view.used_median or 0) + 20.0, 55, 0.0, None, 82,
        )
        comparison = OwnershipComparison(
            "demo-used", OwnershipRecommendation.PREFER_USED, 82, [projection],
            None, -120.0, 15.0, 1250.0, None, [],
            ["Structured demo comparison"], [],
        )
        market = {"new": _market_view(new_snapshot), "used": _market_view(used_snapshot)}
        new_vs_used = {"recommendation": decision.new_vs_used_recommendation.value, "confidence": decision.confidence, "factors": [{"name": "decision", "explanation": decision.reasons[0], "impact": decision.buy_score}]}
        ownership = {"acquisition_price": projection.acquisition_cost, "gross_ownership_cost": projection.gross_ownership_cost_with_resale, "protection_score": projection.protection_score, "risk_cost": projection.risk_cost, "estimated_resale": projection.estimated_resale_value, "break_even_used_price": comparison.break_even_target_used_price, "recommendation": comparison.recommendation.value, "confidence": comparison.confidence, "warnings": comparison.warnings}
        listings = [{"source": "Demo Market", "title": view.display_name + " used", "price": view.used_median, "currency": "EUR", "country": "Italy", "condition": "USED", "defects": [], "accessories": [], "recommendation": "MONITOR", "url": f"https://example.invalid/listings/{view.id}"}]
    memory_decisions = [entry for entry in decisions if entry.product_id == view.id]
    return {
        "product": view, "aliases": view.aliases, "market": market or {"new": None, "used": None},
        "new_vs_used": new_vs_used, "listings": listings, "ownership": ownership,
        "memory": {"owned": view.owned, "wishlist": view.wishlist, "wishlist_priority": view.wishlist_priority, "target_price": view.target_price, "target_currency": view.target_currency, "recent_decisions": [{"decision": item.decision, "score": item.decision_score, "created_at": item.created_at.isoformat()} for item in memory_decisions]},
        "warnings": [] if rich else ["Market data is not yet available."],
    }


def _add_radar_data(
    data: DashboardData, store: RadarStore, products: Sequence[Product],
    aliases: Sequence[ProductAlias],
) -> DashboardData:
    """Compose product workspaces and the global inbox from one listing index."""
    all_listings = store.load_listings()
    builder = ProductWorkspaceBuilder(products, all_listings, aliases)
    product_by_id = {item.id: item for item in products}
    for product_id, detail in data.details.items():
        analysis = builder.analysis.get(product_id, {})
        _update_product_market_view(data, product_id, analysis.get("market", {}))
        current = next(item for item in data.products if item.id == product_id)
        workspace = builder.build(
            product_by_id[product_id], current, detail["memory"], detail["warnings"]
        )
        enriched = builder.enrich_product(current, workspace)
        workspace = replace(workspace, product=enriched)
        index = next(i for i, item in enumerate(data.products) if item.id == product_id)
        data.products[index] = enriched
        detail.update({
            "product": enriched,
            "workspace": workspace,
            "listings": workspace.active_offers,
            "listing_market": workspace.market_snapshots,
            "listing_decisions": workspace.listing_analyses,
            "ownership_comparisons": workspace.available_comparisons,
            "default_comparison_key": workspace.selected_comparison,
            "comparison_options": workspace.comparison_options,
            "overall_conclusion": workspace.overall_conclusion,
            "comparison_conclusions": workspace.comparison_conclusions,
        })
    inbox = builder.listing_views()
    runs = store.load_runs()
    health = store.load_health()
    latest = max(runs, key=lambda item: item.started_at) if runs else None
    data.context.update({
        "live_listing_count": sum(bool(item["active"]) for item in inbox),
        "listing_review_count": sum(bool(item["needs_review"]) for item in inbox),
        "latest_radar_status": latest.status.value if latest else None,
        "latest_radar_ignored_count": latest.listing_count_ignored if latest else 0,
        "radar_source_health": [
            {"source_id": item.source_id, "status": item.status,
             "checked_at": item.checked_at.isoformat(),
             "relevant_persisted_count": item.relevant_persisted_count}
            for item in health
        ],
        "live_listings": inbox,
    })
    return data


def _update_product_market_view(data, product_id, market):
    currencies = sorted({value["currency"] for value in market.values()})
    if not currencies:
        return
    currency = next((value for value in currencies
        if f"{value}:NEW" in market and f"{value}:USED" in market),currencies[0])
    new = market.get(f"{currency}:NEW",{})
    used = market.get(f"{currency}:USED",{})
    confidence_values = [value.get("market_confidence") for value in (new,used) if value.get("market_confidence") is not None]
    index = next((position for position,item in enumerate(data.products) if item.id==product_id),None)
    if index is None:
        return
    updated = replace(data.products[index],new_median=new.get("median"),used_median=used.get("median"),
        market_currency=currency,market_confidence=min(confidence_values) if confidence_values else None)
    data.products[index]=updated;data.details[product_id]["product"]=updated


def _snapshot(product_id: str, segment: str, median: Optional[float]) -> MarketSnapshot:
    return MarketSnapshot(
        product_id, "Italy", ["Germany", "Italy"], "EUR", segment,
        datetime(2026, 8, 1, tzinfo=timezone.utc), 12, 11, 1, median,
        median, median, (median or 0) * .85, (median or 0) * 1.15, 50.0,
        (median or 0) * .8, (median or 0) * .9, (median or 0) * 1.1,
        (median or 0) * 1.2, 5.0, 80, -2.0, -4.0, -6.0, 10.0,
        18.0, 90.0,
    )


def _market_view(snapshot: MarketSnapshot) -> Dict[str, object]:
    return {
        "currency": snapshot.currency, "median": snapshot.median_price,
        "percentile_25": snapshot.percentile_25,
        "percentile_75": snapshot.percentile_75,
        "sample_size": snapshot.valid_sample_size,
        "market_confidence": snapshot.market_confidence,
        "source_countries": snapshot.source_countries,
        "outlier_count": snapshot.outlier_count, "trend_30d": snapshot.trend_30d,
        "depreciation_12_months": snapshot.estimated_12_month_depreciation,
        "depreciation_24_months": snapshot.estimated_24_month_depreciation,
    }
