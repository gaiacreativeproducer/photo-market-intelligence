"""Candidate deduplication, persistence, and best-effort channel delivery."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time

from .models import DeliveryStatus, DigestMode, Severity
from .rules import health_candidates, listing_candidates, run_candidate

LEVEL = {Severity.INFO: 0, Severity.NOTICE: 1, Severity.IMPORTANT: 2, Severity.CRITICAL: 3}


class NotificationEngine:
    def __init__(self, store, channels=(), now=None):
        self.store = store; self.channels = list(channels)
        self.now = now or datetime.now().astimezone

    def evaluate_radar(self, run, new_listings, watches, previous_health, health, dry_run=False):
        if dry_run: return []
        preference = self.store.load_preferences()
        if not preference.enabled: return []
        now = self.now(); candidates = []
        for listing in new_listings:
            candidates.extend(listing_candidates(listing, watches, preference, now))
        candidates.extend(run_candidate(run, now))
        candidates.extend(health_candidates(previous_health, health, preference, now))
        candidates = [item for item in candidates if LEVEL[item.severity] >= LEVEL[preference.minimum_severity]]
        stored = self.store.load(); keys = {item.deduplication_key for item in stored}
        fresh = [item for item in candidates if item.deduplication_key not in keys]
        self.store.save(stored + fresh)
        for item in fresh:
            self._deliver(item, preference)
        return fresh

    def _deliver(self, notification, preference):
        if not self.channels: return
        deferred = preference.digest_mode != DigestMode.IMMEDIATE or _quiet(self.now(), preference)
        values = self.store.load()
        for index, item in enumerate(values):
            if item.notification_id != notification.notification_id: continue
            if deferred:
                values[index] = replace(item, delivery_status=DeliveryStatus.DEFERRED,
                    delivery_message="delivery deferred by quiet hours or digest mode")
            else:
                try:
                    for channel in self.channels: channel.send(item)
                    values[index] = replace(item, delivery_status=DeliveryStatus.DELIVERED,
                        delivered_at=self.now(), delivery_attempts=item.delivery_attempts + 1,
                        delivery_message="delivered")
                except Exception:
                    values[index] = replace(item, delivery_status=DeliveryStatus.FAILED,
                        delivery_attempts=item.delivery_attempts + 1,
                        delivery_message="notification channel failed")
            self.store.save(values); return


def _quiet(now, preference):
    if not preference.quiet_hours_start or not preference.quiet_hours_end: return False
    start = time.fromisoformat(preference.quiet_hours_start)
    end = time.fromisoformat(preference.quiet_hours_end)
    current = now.timetz().replace(tzinfo=None)
    return start <= current < end if start < end else current >= start or current < end
