"""Inventory validation, persistence, and catalog-backed coverage."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from catalog import Product

from .models import InventoryCoverage, OwnedItem, PurchaseCondition
from .storage import (
    INVENTORY_FIELDS, MemoryValidationError, decode_list, encode_list, error,
    read_csv, write_csv_atomic,
)


def load_inventory(path: Path, products: Sequence[Product]) -> List[OwnedItem]:
    product_ids = {product.id for product in products}
    items: List[OwnedItem] = []
    seen = set()
    for row_number, row in enumerate(read_csv(path, INVENTORY_FIELDS), 2):
        item_id = _required(row["item_id"], path, row_number, "item_id")
        product_id = _required(row["product_id"], path, row_number, "product_id")
        if item_id.casefold() in seen:
            error(path, row_number, "item_id", f"duplicate value {item_id!r}")
        seen.add(item_id.casefold())
        if product_id not in product_ids:
            error(path, row_number, "product_id", f"unknown product ID {product_id!r}")
        serial = row["serial_reference"] or None
        _validate_serial(serial, path, row_number)
        items.append(OwnedItem(
            item_id, product_id,
            _date(row["purchase_date"], path, row_number, "purchase_date"),
            _float(row["purchase_price"], path, row_number, "purchase_price"),
            _currency(row["currency"], path, row_number),
            _condition(row["condition_at_purchase"], path, row_number),
            _integer(row["shutter_count_at_purchase"], path, row_number, "shutter_count_at_purchase"),
            _integer(row["current_shutter_count"], path, row_number, "current_shutter_count"),
            _date(row["warranty_until"], path, row_number, "warranty_until"),
            decode_list(row["accessories"], path, row_number, "accessories"),
            serial, row["notes"], _boolean(row["active"], path, row_number),
        ))
    return items


def save_inventory(path: Path, items: Sequence[OwnedItem]) -> None:
    write_csv_atomic(path, INVENTORY_FIELDS, inventory_rows(items))


def inventory_rows(items: Sequence[OwnedItem]) -> List[Dict[str, object]]:
    return [{
        "item_id": item.item_id, "product_id": item.product_id,
        "purchase_date": _format(item.purchase_date),
        "purchase_price": _format(item.purchase_price), "currency": item.currency or "",
        "condition_at_purchase": item.condition_at_purchase.value if item.condition_at_purchase else "",
        "shutter_count_at_purchase": _format(item.shutter_count_at_purchase),
        "current_shutter_count": _format(item.current_shutter_count),
        "warranty_until": _format(item.warranty_until),
        "accessories": encode_list(item.accessories),
        "serial_reference": item.serial_reference or "", "notes": item.notes,
        "active": "true" if item.active else "false",
    } for item in items]


def summarize_inventory(items: Sequence[OwnedItem], products: Sequence[Product]) -> InventoryCoverage:
    by_id = {product.id: product for product in products}
    active = [item for item in items if item.active]
    counts = Counter(item.product_id for item in active)
    cameras: List[str] = []
    primes: List[str] = []
    zooms: List[str] = []
    cinema: List[str] = []
    accessories: List[str] = []
    families = set()
    focal: Dict[str, List[str]] = {"ULTRA_WIDE": [], "STANDARD": [], "TELEPHOTO": []}
    unknown: List[str] = []
    for product_id in dict.fromkeys(item.product_id for item in active):
        product = by_id[product_id]
        category = product.category.casefold()
        product_type = product.product_type.casefold()
        if category == "camera": cameras.append(product_id)
        if "cinema lens" in category or "cinema lens" in product_type: cinema.append(product_id)
        elif "lens" not in category and "lens" not in product_type: accessories.append(product_id)
        if "prime" in product_type: primes.append(product_id)
        if "zoom" in product_type: zooms.append(product_id)
        families.add(f"{product.brand.casefold()}:{_family(product.model)}")
        if "lens" in category or "lens" in product_type:
            categories = _focal_categories(product.model, "zoom" in product_type)
            if categories is None:
                unknown.append(product_id)
            else:
                for focal_category in categories:
                    focal[focal_category].append(product_id)
    return InventoryCoverage(
        cameras, primes, zooms, cinema, accessories,
        {key: value for key, value in counts.items() if value > 1},
        sorted(families), focal, unknown,
    )


def _focal_categories(model: str, zoom: bool) -> Optional[List[str]]:
    match = re.search(r"(?<![\d.])(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?\s*mm\b", model, re.I)
    if not match or bool(match.group(2)) != zoom:
        return None
    low = int(match.group(1))
    high = int(match.group(2) or match.group(1))
    if low > high:
        return None
    result = []
    if low < 24: result.append("ULTRA_WIDE")
    if low <= 69 and high >= 24: result.append("STANDARD")
    if high >= 70: result.append("TELEPHOTO")
    return result


def _family(model: str) -> str:
    return " ".join(re.sub(r"\b(?:i{1,3}|iv|v|ii)\b$", "", model, flags=re.I).casefold().split())


def _required(value: str, path: Path, row: int, field: str) -> str:
    if not value: error(path, row, field, "required value is missing")
    return value


def _date(value: str, path: Path, row: int, field: str) -> Optional[date]:
    if not value: return None
    try: return date.fromisoformat(value)
    except ValueError: error(path, row, field, f"invalid ISO date {value!r}")


def _float(value: str, path: Path, row: int, field: str) -> Optional[float]:
    if not value: return None
    try: result = float(value)
    except ValueError: error(path, row, field, f"expected a number, got {value!r}")
    if result < 0: error(path, row, field, "must not be negative")
    return result


def _integer(value: str, path: Path, row: int, field: str) -> Optional[int]:
    if not value: return None
    try: result = int(value)
    except ValueError: error(path, row, field, f"expected an integer, got {value!r}")
    if result < 0: error(path, row, field, "must not be negative")
    return result


def _currency(value: str, path: Path, row: int) -> Optional[str]:
    if not value: return None
    if not re.fullmatch(r"[A-Za-z]{3}", value): error(path, row, "currency", "expected a three-letter currency")
    return value.upper()


def _condition(value: str, path: Path, row: int) -> Optional[PurchaseCondition]:
    if not value: return None
    try: return PurchaseCondition(value)
    except ValueError: error(path, row, "condition_at_purchase", f"invalid value {value!r}")


def _boolean(value: str, path: Path, row: int) -> bool:
    if value.casefold() in {"true", "1"}: return True
    if value.casefold() in {"false", "0"}: return False
    error(path, row, "active", "expected true or false")


def _validate_serial(value: Optional[str], path: Path, row: int) -> None:
    if value is None: return
    if len(value) > 20: error(path, row, "serial_reference", "must be at most 20 characters")
    if re.search(r"\b(?:serial|seriale|s/n)\b\s*[:#-]?\s*[A-Z0-9]{6,}", value, re.I):
        error(path, row, "serial_reference", "full serial identifiers are not allowed")
    if "*" not in value and re.fullmatch(r"(?=.*\d)[A-Z0-9-]{10,}", value, re.I):
        error(path, row, "serial_reference", "use an internal label or masked suffix")


def _format(value: object) -> str:
    return "" if value is None else str(value)
