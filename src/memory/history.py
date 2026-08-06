"""Privacy-safe decision history with normalized listing URLs."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from catalog import Product

from .models import DecisionHistoryEntry
from .storage import HISTORY_FIELDS, decode_list, encode_list, error, read_csv, write_csv_atomic


TRACKING_PARAMETERS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "ref", "tracking",
}
EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\s().-]*){8,15}(?!\w)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")
ADDRESS = re.compile(r"\b(?:via|viale|piazza|corso|street|st\.|road|rd\.)\s+[A-Za-zÀ-ÿ' -]+\s+\d{1,5}\b", re.I)
TOKEN = re.compile(r"\b(?:api[_ -]?key|token|password|passwd|secret)\s*[:=]\s*\S+", re.I)


def normalize_listing_url(value: str, path: Path, row: int) -> str:
    try: parsed = urlsplit(value)
    except ValueError as exc: error(path, row, "listing_url", str(exc))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        error(path, row, "listing_url", "only absolute http and https URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        error(path, row, "listing_url", "embedded credentials are not allowed")
    query = urlencode([(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True) if key.casefold() not in TRACKING_PARAMETERS], doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def load_decision_history(path: Path, products: Sequence[Product]) -> List[DecisionHistoryEntry]:
    product_ids = {product.id for product in products}
    entries: List[DecisionHistoryEntry] = []
    seen = set()
    for row_number, row in enumerate(read_csv(path, HISTORY_FIELDS), 2):
        for field in ("entry_id", "product_id", "listing_url", "source", "decision", "created_at"):
            if not row[field]: error(path, row_number, field, "required value is missing")
        if row["entry_id"].casefold() in seen: error(path, row_number, "entry_id", "duplicate value")
        seen.add(row["entry_id"].casefold())
        if row["product_id"] not in product_ids: error(path, row_number, "product_id", f"unknown product ID {row['product_id']!r}")
        reasons = decode_list(row["reasons"], path, row_number, "reasons")
        for text in reasons: _validate_private_text(text, path, row_number, "reasons")
        _validate_private_text(row["rejected_reason"], path, row_number, "rejected_reason")
        try:
            created = datetime.fromisoformat(row["created_at"])
            score = int(row["decision_score"]) if row["decision_score"] else None
            price = float(row["observed_price"]) if row["observed_price"] else None
        except ValueError as exc: error(path, row_number, "value", str(exc))
        if score is not None and not 0 <= score <= 100: error(path, row_number, "decision_score", "must be from 0 to 100")
        if price is not None and price < 0: error(path, row_number, "observed_price", "must not be negative")
        entries.append(DecisionHistoryEntry(
            row["entry_id"], row["product_id"], normalize_listing_url(row["listing_url"], path, row_number),
            row["source"], row["decision"], score, row["ownership_recommendation"], price,
            row["currency"].upper() or None, reasons, row["rejected_reason"], created,
        ))
    return entries


def save_decision_history(path: Path, entries: Sequence[DecisionHistoryEntry]) -> None:
    rows: List[Dict[str, object]] = []
    for row_number, entry in enumerate(entries, 2):
        url = normalize_listing_url(entry.listing_url, path, row_number)
        for reason in entry.reasons: _validate_private_text(reason, path, row_number, "reasons")
        _validate_private_text(entry.rejected_reason, path, row_number, "rejected_reason")
        rows.append({
            "entry_id": entry.entry_id, "product_id": entry.product_id,
            "listing_url": url, "source": entry.source, "decision": entry.decision,
            "decision_score": "" if entry.decision_score is None else entry.decision_score,
            "ownership_recommendation": entry.ownership_recommendation,
            "observed_price": "" if entry.observed_price is None else entry.observed_price,
            "currency": entry.currency or "", "reasons": encode_list(entry.reasons),
            "rejected_reason": entry.rejected_reason, "created_at": entry.created_at.isoformat(),
        })
    write_csv_atomic(path, HISTORY_FIELDS, rows)


def _validate_private_text(value: str, path: Path, row: int, field: str) -> None:
    for pattern, label in ((EMAIL, "email address"), (PHONE, "telephone number"), (CARD, "payment-card-like value"), (ADDRESS, "precise street address"), (TOKEN, "credential or token")):
        if pattern.search(value): error(path, row, field, f"obvious {label} is not allowed")
