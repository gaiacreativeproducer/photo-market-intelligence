"""Strict radar configuration, watch, and structured-price import helpers."""

from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence

from catalog import Product

from .models import RadarSource, RadarWatch, SourceType


SOURCE_KEYS = {
    "source_id", "name", "source_type", "endpoint", "enabled", "country",
    "currency", "segment", "request_timeout_seconds", "retry_count",
    "minimum_request_interval_seconds", "mapping", "notes",
}
EBAY_REQUIRED_KEYS = {
    "source_id", "name", "source_type", "enabled", "marketplace_id",
    "country", "currency", "query_limit", "minimum_request_interval_seconds",
}
EBAY_OPTIONAL_KEYS = {"segment_preference", "notes"}
MAPPING_KEYS = {
    "list_path", "external_id", "url", "title", "description", "price",
    "currency", "source_country", "segment", "condition", "detected_at",
    "header_environment", "price_extraction",
}
PRICE_KEYS = {
    "currency_symbol", "currency_code", "decimal_separator",
    "thousands_separator", "allowed_prefixes", "allowed_suffixes",
}
WATCH_FIELDS = (
    "watch_id", "product_id", "query", "condition_preference", "max_price",
    "currency", "source_ids", "active", "priority", "created_at", "updated_at",
)


class RadarValidationError(ValueError): pass


def load_sources(path: Path, allow_private_network: bool = False) -> List[RadarSource]:
    try: root = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise RadarValidationError(f"{path}: {exc}")
    if not isinstance(root, dict) or set(root) != {"sources"} or not isinstance(root["sources"], list):
        raise RadarValidationError(f"{path}: root must contain only a sources array")
    sources = []; seen = set()
    for index, value in enumerate(root["sources"], 1):
        if not isinstance(value, dict): raise RadarValidationError(f"{path}: source {index} must be an object")
        if value.get("source_type") == SourceType.EBAY_BROWSE.value:
            allowed = EBAY_REQUIRED_KEYS | EBAY_OPTIONAL_KEYS
            unknown = set(value) - allowed
            missing = EBAY_REQUIRED_KEYS - set(value)
            if unknown: raise RadarValidationError(f"{path}: source {index}: unknown key {sorted(unknown)[0]!r}")
            if missing: raise RadarValidationError(f"{path}: source {index}: missing key {sorted(missing)[0]!r}")
            if value["source_id"] in seen: raise RadarValidationError(f"{path}: duplicate source_id")
            seen.add(value["source_id"])
            if not isinstance(value["enabled"], bool): raise RadarValidationError(f"{path}: source {index}: enabled must be boolean")
            if value["marketplace_id"] not in {"EBAY_IT","EBAY_DE","EBAY_FR","EBAY_ES","EBAY_GB"}:
                raise RadarValidationError(f"{path}: source {index}: invalid marketplace_id")
            if not re.fullmatch(r"[A-Z]{2}", str(value["country"])): raise RadarValidationError(f"{path}: invalid country")
            if not re.fullmatch(r"[A-Z]{3}", str(value["currency"])): raise RadarValidationError(f"{path}: invalid currency")
            try: query_limit=int(value["query_limit"]); interval=float(value["minimum_request_interval_seconds"])
            except (TypeError,ValueError): raise RadarValidationError(f"{path}: source {index}: invalid numeric configuration")
            if not 1 <= query_limit <= 200: raise RadarValidationError(f"{path}: source {index}: query_limit must be from 1 to 200")
            if interval < 0: raise RadarValidationError(f"{path}: source {index}: minimum_request_interval_seconds cannot be negative")
            segment=str(value.get("segment_preference","EITHER")).upper()
            if segment not in {"NEW","USED","EITHER"}: raise RadarValidationError(f"{path}: source {index}: invalid segment_preference")
            sources.append(RadarSource(
                str(value["source_id"]),str(value["name"]),SourceType.EBAY_BROWSE,"",
                bool(value["enabled"]),str(value["country"]),str(value["currency"]),segment,
                15.0,1,interval,{},str(value.get("notes","")),
                str(value["marketplace_id"]),query_limit,
            ))
            continue
        unknown = set(value) - SOURCE_KEYS
        missing = SOURCE_KEYS - set(value)
        if unknown: raise RadarValidationError(f"{path}: source {index}: unknown key {sorted(unknown)[0]!r}")
        if missing: raise RadarValidationError(f"{path}: source {index}: missing key {sorted(missing)[0]!r}")
        if value["source_id"] in seen: raise RadarValidationError(f"{path}: duplicate source_id")
        seen.add(value["source_id"])
        try: source_type = SourceType(value["source_type"])
        except ValueError: raise RadarValidationError(f"{path}: source {index}: invalid source_type")
        mapping = value["mapping"]
        if not isinstance(mapping, dict): raise RadarValidationError(f"{path}: source {index}: mapping must be an object")
        unknown_mapping = set(mapping) - MAPPING_KEYS
        if unknown_mapping: raise RadarValidationError(f"{path}: source {index}: unknown mapping key {sorted(unknown_mapping)[0]!r}")
        if "price_regex" in mapping: raise RadarValidationError(f"{path}: arbitrary price_regex is not allowed")
        price_config = mapping.get("price_extraction")
        if price_config is not None:
            if not isinstance(price_config, dict) or set(price_config) - PRICE_KEYS:
                raise RadarValidationError(f"{path}: source {index}: invalid price_extraction keys")
            for key, item in price_config.items():
                values = item if isinstance(item, list) else [item]
                if any(not isinstance(part, str) or len(part) > 20 for part in values):
                    raise RadarValidationError(f"{path}: source {index}: invalid price_extraction {key}")
        if value["segment"] not in {"NEW", "USED"}: raise RadarValidationError(f"{path}: invalid segment")
        if not re.fullmatch(r"[A-Z]{2}", value["country"]): raise RadarValidationError(f"{path}: invalid country")
        if not re.fullmatch(r"[A-Z]{3}", value["currency"]): raise RadarValidationError(f"{path}: invalid currency")
        sources.append(RadarSource(
            str(value["source_id"]), str(value["name"]), source_type,
            str(value["endpoint"]), bool(value["enabled"]), str(value["country"]),
            str(value["currency"]), str(value["segment"]),
            float(value["request_timeout_seconds"]), int(value["retry_count"]),
            float(value["minimum_request_interval_seconds"]), dict(mapping),
            str(value["notes"]),
        ))
    return sources


def load_watches(path: Path, products: Sequence[Product], sources: Sequence[RadarSource]) -> List[RadarWatch]:
    product_ids = {item.id for item in products}; source_ids = {item.source_id for item in sources}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(WATCH_FIELDS): raise RadarValidationError(f"{path}: invalid header")
        result=[]; active_keys=set(); seen=set()
        for row_number,row in enumerate(reader,2):
            watch_id=(row["watch_id"] or "").strip(); product_id=(row["product_id"] or "").strip(); query=(row["query"] or "").strip()
            if not watch_id or watch_id in seen: raise RadarValidationError(f"{path}: row {row_number}: invalid watch_id")
            seen.add(watch_id)
            if not product_id and not query: raise RadarValidationError(f"{path}: row {row_number}: product_id or query required")
            if product_id and product_id not in product_ids: raise RadarValidationError(f"{path}: row {row_number}: unknown product_id")
            try: selected=json.loads(row["source_ids"] or "[]")
            except json.JSONDecodeError: raise RadarValidationError(f"{path}: row {row_number}: invalid source_ids")
            if not isinstance(selected,list) or any(item not in source_ids for item in selected): raise RadarValidationError(f"{path}: row {row_number}: unknown source_id")
            active=_bool(row["active"],path,row_number); condition=row["condition_preference"]
            if condition not in {"NEW","USED","EITHER"}: raise RadarValidationError(f"{path}: row {row_number}: invalid condition")
            maximum=float(row["max_price"]) if row["max_price"] else None
            key=(product_id.casefold(),query.casefold(),tuple(sorted(selected)))
            if active and key in active_keys: raise RadarValidationError(f"{path}: row {row_number}: duplicate active watch")
            if active: active_keys.add(key)
            result.append(RadarWatch(watch_id,product_id,query,condition,maximum,row["currency"],selected,active,row["priority"],datetime.fromisoformat(row["created_at"]),datetime.fromisoformat(row["updated_at"])))
    return result


def extract_structured_price(text: str, config: Dict[str, object]) -> float:
    prefixes = [str(item) for item in config.get("allowed_prefixes", [])]
    suffixes = [str(item) for item in config.get("allowed_suffixes", [])]
    symbols = [str(config.get("currency_symbol", "")), str(config.get("currency_code", ""))]
    markers = [item for item in prefixes + suffixes + symbols if item]
    if not markers or not any(marker.casefold() in text.casefold() for marker in markers):
        raise ValueError("configured currency marker is absent")
    decimal=str(config.get("decimal_separator", ".")); thousands=str(config.get("thousands_separator", ","))
    tokens=re.findall(r"\d[\d., ]{0,18}\d|\d", text)
    if len(tokens)!=1: raise ValueError("price text must contain exactly one bounded numeric token")
    normalized=tokens[0].replace(" ","")
    if thousands: normalized=normalized.replace(thousands,"")
    if decimal and decimal != ".": normalized=normalized.replace(decimal,".")
    value=float(normalized)
    if not math.isfinite(value) or value<0: raise ValueError("invalid price")
    return value


def _bool(value,path,row):
    if value.casefold() in {"true","1"}: return True
    if value.casefold() in {"false","0"}: return False
    raise RadarValidationError(f"{path}: row {row}: invalid boolean")
