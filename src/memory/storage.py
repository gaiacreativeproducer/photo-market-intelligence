"""Strict schemas, initialization, and atomic persistence for user memory."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

from .models import PurchaseCondition, RiskTolerance, UserPreferences


INVENTORY_FIELDS = (
    "item_id", "product_id", "purchase_date", "purchase_price", "currency",
    "condition_at_purchase", "shutter_count_at_purchase", "current_shutter_count",
    "warranty_until", "accessories", "serial_reference", "notes", "active",
)
WISHLIST_FIELDS = (
    "wishlist_id", "product_id", "target_price", "currency", "priority",
    "purchase_condition_preference", "target_date", "reason", "status",
    "created_at", "updated_at",
)
HISTORY_FIELDS = (
    "entry_id", "product_id", "listing_url", "source", "decision",
    "decision_score", "ownership_recommendation", "observed_price", "currency",
    "reasons", "rejected_reason", "created_at",
)
PREFERENCE_FIELDS = {
    "target_market_country", "preferred_currency", "default_purchase_condition",
    "risk_tolerance", "warranty_importance", "resale_importance",
    "weight_sensitivity", "brand_preferences", "excluded_brands",
    "preferred_sources", "excluded_sources", "notification_threshold", "notes",
}
TEMPLATE_NAMES = {
    "user_inventory.csv": "user_inventory.example.csv",
    "user_wishlist.csv": "user_wishlist.example.csv",
    "user_decision_history.csv": "user_decision_history.example.csv",
    "user_preferences.json": "user_preferences.example.json",
}


class MemoryValidationError(ValueError):
    """Raised when user-memory data violates its strict schema."""


def error(path: Path, row: object, field: str, message: str) -> None:
    raise MemoryValidationError(f"{path}: row {row}, field '{field}': {message}")


def initialize_user_data(template_directory: Path, user_directory: Path) -> None:
    """Create missing runtime files from tracked templates without overwriting."""
    user_directory.mkdir(parents=True, exist_ok=True)
    for runtime_name, template_name in TEMPLATE_NAMES.items():
        destination = user_directory / runtime_name
        if destination.exists():
            continue
        source = template_directory / template_name
        if not source.is_file():
            raise FileNotFoundError(f"required user-memory template not found: {source}")
        _atomic_bytes(destination, source.read_bytes())


def read_csv(path: Path, fields: Sequence[str]) -> List[Dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"required user-memory CSV not found: {path}")
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            actual = reader.fieldnames
            if actual is None:
                error(path, 1, "header", "header is missing")
            unknown = [field for field in actual if field not in fields]
            missing = [field for field in fields if field not in actual]
            if unknown:
                error(path, 1, unknown[0], "unknown column")
            if missing:
                error(path, 1, missing[0], "required column is missing")
            if list(actual) != list(fields):
                error(path, 1, "header", "columns must use the documented order")
            rows = []
            for row_number, row in enumerate(reader, 2):
                if None in row:
                    error(path, row_number, "row", "too many columns")
                rows.append({field: (row.get(field) or "").strip() for field in fields})
            return rows
    except UnicodeDecodeError as exc:
        raise MemoryValidationError(f"{path}: invalid UTF-8: {exc}")
    except csv.Error as exc:
        raise MemoryValidationError(f"{path}: malformed CSV: {exc}")


def read_json(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"required user-memory JSON not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemoryValidationError(f"{path}: malformed JSON: {exc}")
    if not isinstance(value, dict):
        error(path, "JSON", "root", "expected an object")
    unknown = set(value) - PREFERENCE_FIELDS
    missing = PREFERENCE_FIELDS - set(value)
    if unknown:
        error(path, "JSON", sorted(unknown)[0], "unknown key")
    if missing:
        error(path, "JSON", sorted(missing)[0], "required key is missing")
    return value


def encode_list(values: Iterable[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def decode_list(value: str, path: Path, row: int, field: str) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        error(path, row, field, "expected a JSON string array")
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        error(path, row, field, "expected a JSON string array")
    return parsed


def write_csv_atomic(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    temporary = _prepare_csv(path, fields, rows)
    try:
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    _atomic_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def load_preferences(path: Path) -> UserPreferences:
    value = read_json(path)
    for field in ("warranty_importance", "resale_importance", "weight_sensitivity", "notification_threshold"):
        number = value[field]
        if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 100:
            error(path, "JSON", field, "expected an integer from 0 to 100")
    for field in ("brand_preferences", "excluded_brands", "preferred_sources", "excluded_sources"):
        items = value[field]
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            error(path, "JSON", field, "expected a string array")
    try:
        condition = PurchaseCondition(str(value["default_purchase_condition"]))
        risk = RiskTolerance(str(value["risk_tolerance"]))
    except ValueError as exc:
        error(path, "JSON", "value", str(exc))
    preferred_currency = str(value["preferred_currency"]).upper()
    if preferred_currency and (len(preferred_currency) != 3 or not preferred_currency.isalpha()):
        error(path, "JSON", "preferred_currency", "expected a three-letter currency")
    preferred_brands = list(value["brand_preferences"])
    excluded_brands = list(value["excluded_brands"])
    if {item.casefold() for item in preferred_brands} & {item.casefold() for item in excluded_brands}:
        error(path, "JSON", "brand_preferences", "preferred and excluded brands overlap")
    preferred_sources = list(value["preferred_sources"])
    excluded_sources = list(value["excluded_sources"])
    if {item.casefold() for item in preferred_sources} & {item.casefold() for item in excluded_sources}:
        error(path, "JSON", "preferred_sources", "preferred and excluded sources overlap")
    return UserPreferences(
        str(value["target_market_country"]), preferred_currency, condition, risk,
        int(value["warranty_importance"]), int(value["resale_importance"]),
        int(value["weight_sensitivity"]), preferred_brands, excluded_brands,
        preferred_sources, excluded_sources, int(value["notification_threshold"]),
        str(value["notes"]),
    )


def save_preferences(path: Path, preferences: UserPreferences) -> None:
    write_json_atomic(path, {
        "target_market_country": preferences.target_market_country,
        "preferred_currency": preferences.preferred_currency,
        "default_purchase_condition": preferences.default_purchase_condition.value,
        "risk_tolerance": preferences.risk_tolerance.value,
        "warranty_importance": preferences.warranty_importance,
        "resale_importance": preferences.resale_importance,
        "weight_sensitivity": preferences.weight_sensitivity,
        "brand_preferences": preferences.brand_preferences,
        "excluded_brands": preferences.excluded_brands,
        "preferred_sources": preferences.preferred_sources,
        "excluded_sources": preferences.excluded_sources,
        "notification_threshold": preferences.notification_threshold,
        "notes": preferences.notes,
    })


def prepare_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> Path:
    return _prepare_csv(path, fields, rows)


def restore_bytes_atomic(path: Path, content: bytes) -> None:
    _atomic_bytes(path, content)


def _prepare_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()
