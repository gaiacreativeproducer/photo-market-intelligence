"""Deterministic notification candidate rules over existing structured evidence."""
from __future__ import annotations

import uuid
from datetime import datetime

from radar.models import RunStatus

from .models import Notification, NotificationPreference, NotificationType, Severity


def listing_candidates(listing, watches, preference: NotificationPreference, now: datetime):
    if not preference.enabled or not listing.active:
        return []
    matched = [watch for watch in watches if watch.active and (
        (watch.product_id and watch.product_id == listing.product_id) or
        (watch.query and watch.query.casefold() in listing.title.casefold())
    ) and (not watch.source_ids or listing.source_id in watch.source_ids)]
    if preference.active_wishlist_only and not matched:
        return []
    if listing.recognition_confidence < preference.minimum_recognition_confidence:
        return []
    values = []
    for watch in matched or [None]:
        watch_id = watch.watch_id if watch else "catalog"
        evidence = {"recognition_confidence": listing.recognition_confidence,
                    "description_confidence": listing.description_confidence}
        if preference.maximum_price is not None:
            if listing.currency and preference.maximum_price_currency and listing.currency == preference.maximum_price_currency:
                if listing.price is not None and listing.price > preference.maximum_price:
                    continue
                evidence["global_maximum_compared"] = True
            else:
                evidence["global_maximum_note"] = "currency mismatch; maximum not compared"
        if preference.notify_new_listing:
            values.append(_notification(NotificationType.NEW_MATCH, Severity.NOTICE,
                "New watched listing", listing.title, listing, now,
                f"NEW_MATCH:{listing.listing_id}:{watch_id}", evidence))
        if (preference.notify_high_confidence_match and listing.recognition_confidence >= 90
                and listing.description_confidence >= 80
                and not any("critical" in str(item).casefold() for item in listing.warnings)):
            values.append(_notification(NotificationType.HIGH_CONFIDENCE_MATCH, Severity.IMPORTANT,
                "High-confidence match", listing.title, listing, now,
                f"HIGH_CONFIDENCE_MATCH:{listing.listing_id}:{watch_id}", evidence))
        if (preference.notify_price_below_target and watch and watch.max_price is not None
                and listing.price is not None and listing.currency == watch.currency
                and listing.price <= watch.max_price):
            key = f"PRICE_BELOW_TARGET:{listing.listing_id}:{watch_id}:{watch.currency}:{watch.max_price:.2f}"
            values.append(_notification(NotificationType.PRICE_BELOW_TARGET, Severity.IMPORTANT,
                "Listing reached target price", listing.title, listing, now, key,
                {**evidence, "price": listing.price, "target_price": watch.max_price,
                 "currency": listing.currency}))
    return values


def run_candidate(run, now):
    kind = {RunStatus.PARTIAL: NotificationType.RADAR_PARTIAL,
            RunStatus.FAILED: NotificationType.RADAR_FAILED}.get(run.status)
    if not kind: return []
    severity = Severity.IMPORTANT if kind == NotificationType.RADAR_PARTIAL else Severity.CRITICAL
    return [Notification(uuid.uuid4().hex, kind, severity, kind.value.replace("_", " ").title(),
                         "Review radar source health.", "", "", "", now, False, False,
                         "/", {"run_id": run.run_id, "source_failure_count": run.source_failure_count},
                         f"{kind.value}:{run.run_id}")]


def health_candidates(previous, current, preference, now):
    values = []
    before = {item.source_id: item.status for item in previous}
    for item in current:
        old = before.get(item.source_id)
        if item.status == "FAILED" and old != "FAILED" and preference.notify_connector_failure:
            values.append(_system(NotificationType.CONNECTOR_FAILED, Severity.CRITICAL, item.source_id, now, "failed"))
        elif item.status == "HEALTHY" and old == "FAILED" and preference.notify_connector_recovery:
            values.append(_system(NotificationType.CONNECTOR_RECOVERED, Severity.NOTICE, item.source_id, now, "healthy"))
    return values


def manual_review_candidate(result_id, recommendation, reasons, product_id="", listing_id="", now=None):
    if not result_id or recommendation != "MANUAL_REVIEW" or not (product_id or listing_id) or not reasons:
        return []
    now = now or datetime.now().astimezone()
    return [Notification(uuid.uuid4().hex, NotificationType.MANUAL_REVIEW_REQUIRED,
        Severity.IMPORTANT, "Manual review required", str(reasons[0])[:200], product_id,
        listing_id, "", now, False, False, "/", {"result_id": result_id},
        f"MANUAL_REVIEW_REQUIRED:{result_id}")]


def _notification(kind, severity, title, message, listing, now, key, evidence):
    return Notification(uuid.uuid4().hex, kind, severity, title, message[:200],
        listing.product_id, listing.listing_id, listing.source_id, now, False, False,
        f"/product.html?id={listing.product_id}" if listing.product_id else "/",
        evidence, key)


def _system(kind, severity, source_id, now, state):
    return Notification(uuid.uuid4().hex, kind, severity, kind.value.replace("_", " ").title(),
        f"Source {source_id} is {state}.", "", "", source_id, now, False, False,
        "/", {"status": state}, f"{kind.value}:{source_id}:{state}")
