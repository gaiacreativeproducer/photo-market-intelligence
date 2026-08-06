"""Smart-wishlist validation, persistence, flags, and purchase lifecycle."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from catalog import Product

from .inventory import inventory_rows, summarize_inventory
from .models import (
    OwnedItem, PurchaseCondition, UserPreferences, WishlistContext, WishlistFlag,
    WishlistItem, WishlistPriority, WishlistStatus,
)
from .storage import (
    INVENTORY_FIELDS, WISHLIST_FIELDS, error, prepare_csv, read_csv,
    restore_bytes_atomic, write_csv_atomic,
)


FLAG_ORDER = {flag: index for index, flag in enumerate(WishlistFlag)}


def load_wishlist(path: Path, products: Sequence[Product]) -> List[WishlistItem]:
    product_ids = {product.id for product in products}
    items: List[WishlistItem] = []
    seen_ids = set()
    active_keys = set()
    for row_number, row in enumerate(read_csv(path, WISHLIST_FIELDS), 2):
        for field in ("wishlist_id", "product_id", "priority", "purchase_condition_preference", "status", "created_at", "updated_at"):
            if not row[field]: error(path, row_number, field, "required value is missing")
        if row["wishlist_id"].casefold() in seen_ids:
            error(path, row_number, "wishlist_id", "duplicate value")
        seen_ids.add(row["wishlist_id"].casefold())
        if row["product_id"] not in product_ids:
            error(path, row_number, "product_id", f"unknown product ID {row['product_id']!r}")
        try:
            priority = WishlistPriority(row["priority"])
            condition = PurchaseCondition(row["purchase_condition_preference"])
            status = WishlistStatus(row["status"])
            created = datetime.fromisoformat(row["created_at"])
            updated = datetime.fromisoformat(row["updated_at"])
            target_date = date.fromisoformat(row["target_date"]) if row["target_date"] else None
            target_price = float(row["target_price"]) if row["target_price"] else None
        except ValueError as exc:
            error(path, row_number, "value", str(exc))
        if target_price is not None and target_price < 0:
            error(path, row_number, "target_price", "must not be negative")
        currency = row["currency"].upper() or None
        if currency and (len(currency) != 3 or not currency.isalpha()):
            error(path, row_number, "currency", "expected a three-letter currency")
        key = (row["product_id"], condition.value)
        if status == WishlistStatus.ACTIVE and key in active_keys:
            error(path, row_number, "purchase_condition_preference", "duplicate active product and condition preference")
        if status == WishlistStatus.ACTIVE: active_keys.add(key)
        items.append(WishlistItem(
            row["wishlist_id"], row["product_id"], target_price, currency,
            priority, condition, target_date, row["reason"], status, created, updated,
        ))
    return items


def save_wishlist(path: Path, items: Sequence[WishlistItem]) -> None:
    write_csv_atomic(path, WISHLIST_FIELDS, wishlist_rows(items))


def wishlist_rows(items: Sequence[WishlistItem]) -> List[Dict[str, object]]:
    return [{
        "wishlist_id": item.wishlist_id, "product_id": item.product_id,
        "target_price": "" if item.target_price is None else item.target_price,
        "currency": item.currency or "", "priority": item.priority.value,
        "purchase_condition_preference": item.purchase_condition_preference.value,
        "target_date": item.target_date or "", "reason": item.reason,
        "status": item.status.value, "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    } for item in items]


def wishlist_contexts(
    wishlist: Sequence[WishlistItem], inventory: Sequence[OwnedItem],
    products: Sequence[Product], preferences: UserPreferences, as_of: date,
) -> List[WishlistContext]:
    by_id = {product.id: product for product in products}
    owned_ids = {item.product_id for item in inventory if item.active}
    coverage = summarize_inventory(inventory, products)
    active = [item for item in wishlist if item.status == WishlistStatus.ACTIVE]
    results = []
    for item in active:
        flags: List[WishlistFlag] = []
        reasons: List[str] = []
        product = by_id[item.product_id]
        if item.product_id in owned_ids:
            _add(flags, reasons, WishlistFlag.ALREADY_OWNED, "The exact product is active in inventory.")
        preferred = preferences.default_purchase_condition
        if preferred != PurchaseCondition.EITHER and item.purchase_condition_preference not in (preferred, PurchaseCondition.EITHER):
            _add(flags, reasons, WishlistFlag.CONDITION_CONFLICT, f"Wishlist condition {item.purchase_condition_preference.value} conflicts with preference {preferred.value}.")
        if item.currency and preferences.preferred_currency and item.currency != preferences.preferred_currency:
            _add(flags, reasons, WishlistFlag.CURRENCY_CONFLICT, f"Wishlist currency {item.currency} differs from preferred {preferences.preferred_currency}.")
        if item.target_date and item.target_date < as_of:
            _add(flags, reasons, WishlistFlag.TARGET_DATE_PASSED, f"Target date {item.target_date} is before {as_of}.")
        wanted_categories = _categories(product)
        owned_categories = {key for key, values in coverage.focal_categories.items() if values}
        same_shape = coverage.zooms if "zoom" in product.product_type.casefold() else coverage.primes
        if wanted_categories is not None:
            if set(wanted_categories) & owned_categories and same_shape:
                _add(flags, reasons, WishlistFlag.POSSIBLE_REDUNDANCY, "Structured focal category and prime/zoom type overlap active inventory.")
            if set(wanted_categories) - owned_categories:
                _add(flags, reasons, WishlistFlag.COMPLEMENTS_INVENTORY, "Structured focal coverage adds a category absent from active inventory.")
        if any(other.product_id == item.product_id and other.purchase_condition_preference != item.purchase_condition_preference for other in active if other.wishlist_id != item.wishlist_id):
            _add(flags, reasons, WishlistFlag.DUPLICATE_PRODUCT, "Another active wishlist item targets this product under a different condition preference.")
        if item.target_price is None:
            _add(flags, reasons, WishlistFlag.TARGET_PRICE_MISSING, "No target price is set.")
        if not flags:
            _add(flags, reasons, WishlistFlag.NONE, "No contextual flag applies.")
        paired = sorted(zip(flags, reasons), key=lambda pair: FLAG_ORDER[pair[0]])
        results.append(WishlistContext(item.wishlist_id, item.product_id, [p[0] for p in paired], [p[1] for p in paired]))
    return results


def record_purchase(
    inventory_path: Path, wishlist_path: Path, inventory: Sequence[OwnedItem],
    wishlist: Sequence[WishlistItem], purchased: OwnedItem, updated_at: datetime,
    products: Sequence[Product],
) -> None:
    """Atomically replace inventory and wishlist, rolling back either on failure."""
    new_inventory = [item for item in inventory if item.item_id != purchased.item_id] + [purchased]
    close = {PurchaseCondition.EITHER}
    if purchased.condition_at_purchase is not None:
        close.add(purchased.condition_at_purchase)
    new_wishlist = [
        replace(item, status=WishlistStatus.PURCHASED, updated_at=updated_at)
        if item.status == WishlistStatus.ACTIVE and item.product_id == purchased.product_id and item.purchase_condition_preference in close
        else item for item in wishlist
    ]
    inventory_temp: Optional[Path] = None
    wishlist_temp: Optional[Path] = None
    inventory_backup = inventory_path.read_bytes() if inventory_path.exists() else None
    wishlist_backup = wishlist_path.read_bytes() if wishlist_path.exists() else None
    try:
        inventory_temp = prepare_csv(inventory_path, INVENTORY_FIELDS, inventory_rows(new_inventory))
        wishlist_temp = prepare_csv(wishlist_path, WISHLIST_FIELDS, wishlist_rows(new_wishlist))
        from .inventory import load_inventory
        load_inventory(inventory_temp, products)
        load_wishlist(wishlist_temp, products)
        os.replace(str(inventory_temp), str(inventory_path))
        inventory_temp = None
        os.replace(str(wishlist_temp), str(wishlist_path))
        wishlist_temp = None
    except Exception:
        if inventory_backup is None:
            inventory_path.unlink(missing_ok=True)
        else:
            restore_bytes_atomic(inventory_path, inventory_backup)
        if wishlist_backup is None:
            wishlist_path.unlink(missing_ok=True)
        else:
            restore_bytes_atomic(wishlist_path, wishlist_backup)
        raise
    finally:
        if inventory_temp is not None:
            inventory_temp.unlink(missing_ok=True)
        if wishlist_temp is not None:
            wishlist_temp.unlink(missing_ok=True)


def _categories(product: Product) -> Optional[List[str]]:
    from .inventory import _focal_categories
    if "lens" not in product.category.casefold() and "lens" not in product.product_type.casefold(): return None
    return _focal_categories(product.model, "zoom" in product.product_type.casefold())


def _add(flags: List[WishlistFlag], reasons: List[str], flag: WishlistFlag, reason: str) -> None:
    flags.append(flag); reasons.append(reason)
