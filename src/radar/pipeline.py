"""Source-neutral radar execution, relevance filtering, and safe persistence."""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Sequence

from analyzers import DescriptionAnalyzer
from catalog import Product, ProductAlias
from connectors.models import ConnectorError, Listing
from knowledge import ProductMatcher

from .models import (
    RadarError, RadarListing, RadarRun, RadarSource, RadarSourceHealth,
    RadarWatch, RunStatus, SourceType,
)
from .persistence import RadarStore
from .source_registry import SourceRegistry, default_registry


_PRIVATE_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"(?<!\w)(?:\+?\d[\s().-]*){8,15}(?!\w)"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    re.compile(r"\b(?:password|passwd|api[_ -]?key|token)\s*[:=]\s*\S+", re.I),
    re.compile(r"\b(?:via|viale|piazza|corso)\s+[A-Za-zÀ-ÿ.' -]{2,40}\s+\d{1,4}\b", re.I),
)


@dataclass(frozen=True)
class PipelineResult:
    run: RadarRun
    listings: List[RadarListing]
    errors: List[RadarError]
    health: List[RadarSourceHealth]
    recognized_count: int = 0
    persisted_relevant_count: int = 0
    ignored_accessory_unmatched_count: int = 0
    needs_review_count: int = 0


class RadarPipeline:
    def __init__(
        self, store: RadarStore, products: Sequence[Product],
        aliases: Sequence[ProductAlias], registry: Optional[SourceRegistry] = None,
        user_directory=None, import_directory=None, allow_private_network: bool = False,
        now=None,
    ) -> None:
        self.store = store
        self.products = list(products)
        self.aliases = list(aliases)
        self.matcher = ProductMatcher(products, aliases)
        self.registry = registry or default_registry()
        self.user_directory = user_directory
        self.import_directory = import_directory
        self.allow_private_network = allow_private_network
        self.now = now or (lambda: datetime.now(timezone.utc))

    def run(
        self, sources: Sequence[RadarSource], watches: Sequence[RadarWatch],
        dry_run: bool = False, stale_days: int = 14,
    ) -> PipelineResult:
        now = self.now()
        run_id = uuid.uuid4().hex
        selected = [source for source in sources if source.enabled]
        existing_runs = self.store.load_runs()
        errors = self.store.load_errors()
        if not dry_run:
            existing_runs, recovered = self._recover_runs(existing_runs, now)
            errors.extend(recovered)
        run = RadarRun(run_id, now, None, RunStatus.DRY_RUN if dry_run else RunStatus.STARTED,
                       len(selected), 0, 0, 0, 0, 0, 0, 0, "run started")
        if not dry_run:
            self.store.save_runs(existing_runs + [run])

        listings = self.store.load_listings()
        existing_listing_ids = {item.listing_id for item in listings}
        previous_health = self.store.load_health()
        health_by_id = {item.source_id: item for item in previous_health}
        current_errors: List[RadarError] = []
        raw_count = normalized_count = new_count = ignored_count = successes = failures = 0
        recognized_count = relevant_count = ignored_unmatched_count = needs_review_count = 0
        product_categories = {item.id: item.category for item in self.products}

        for source in selected:
            started = time.monotonic()
            source_raw = source_normalized = source_relevant = 0
            try:
                connector = self._connector(source, watches)
                connector.validate_source_configuration()
                if hasattr(connector, "fetch_records_for"):
                    batch = connector.fetch_records_for(watches, self.products, self.aliases)
                else:
                    batch = connector.fetch_records()
                source_raw = len(batch.records) + len(batch.errors)
                raw_count += source_raw
                for message in batch.errors:
                    current_errors.append(self._error(run_id, source.source_id, "normalize", "malformed_record", message, now, True))
                for record in batch.records:
                    try:
                        value = connector.normalize_record(record)
                        source_normalized += 1
                        normalized_count += 1
                        listing, relevant, _recognition = self._to_listing(
                            run_id, source, value, record.reference,
                            record.explicitly_supplied, watches, now, product_categories,
                        )
                        confident = bool(
                            _recognition.product_id
                            and _recognition.confidence >= 70
                            and not _recognition.ambiguous
                        )
                        recognized_count += int(confident)
                        if not relevant:
                            ignored_count += 1
                            review = bool(
                                _recognition.ambiguous
                                or (
                                    _recognition.candidates
                                    and not any(
                                        "compatibility reference" in warning
                                        for warning in _recognition.warnings
                                    )
                                )
                            )
                            needs_review_count += int(review)
                            ignored_unmatched_count += int(not review)
                            continue
                        source_relevant += 1
                        relevant_count += 1
                        listings, created = self._upsert(listings, listing)
                        new_count += int(created)
                    except Exception as exc:
                        current_errors.append(self._error(run_id, source.source_id, "normalize", type(exc).__name__, "record could not be normalized", now, True))
                previous = health_by_id.get(source.source_id)
                active_for_source = any(
                    watch.active and (not watch.source_ids or source.source_id in watch.source_ids)
                    for watch in watches
                )
                elapsed_ms = int((time.monotonic() - started) * 1000)
                degraded = bool(batch.errors) or elapsed_ms > source.request_timeout_seconds * 1000
                if previous and previous.relevant_persisted_count > 0 and active_for_source and source_relevant == 0:
                    degraded = True
                successes += 1
                health_by_id[source.source_id] = RadarSourceHealth(
                    source.source_id, "DEGRADED" if degraded else "HEALTHY", now, now,
                    elapsed_ms, source_raw,
                    source_normalized, source_relevant, 0,
                    "source completed with incomplete records" if degraded else "source completed successfully",
                )
            except Exception as exc:
                failures += 1
                message = exc.message if isinstance(exc, ConnectorError) else "source execution failed"
                error_type = exc.error_type if isinstance(exc, ConnectorError) else type(exc).__name__
                current_errors.append(self._error(run_id, source.source_id, "source", error_type, message, now, True))
                previous = health_by_id.get(source.source_id)
                health_by_id[source.source_id] = RadarSourceHealth(
                    source.source_id, "FAILED", now,
                    previous.last_success_at if previous else None,
                    int((time.monotonic() - started) * 1000), source_raw,
                    source_normalized, source_relevant,
                    (previous.consecutive_failures if previous else 0) + 1,
                    message,
                )

        cutoff = now - timedelta(days=stale_days)
        listings = [replace(item, active=False) if item.active and item.last_seen_at < cutoff else item for item in listings]
        status = RunStatus.DRY_RUN if dry_run else (
            RunStatus.COMPLETED if not selected or failures == 0 else
            RunStatus.PARTIAL if successes else RunStatus.FAILED
        )
        final = replace(
            run, finished_at=now, status=status, source_success_count=successes,
            source_failure_count=failures, listing_count_raw=raw_count,
            listing_count_normalized=normalized_count, listing_count_new=new_count,
            listing_count_ignored=ignored_count, incident_count=len(current_errors),
            message="dry run completed" if dry_run else "run completed",
        )
        if not dry_run:
            stored_runs = [final if item.run_id == run_id else item for item in self.store.load_runs()]
            self.store.save_listings(listings)
            self.store.save_errors(errors + current_errors)
            self.store.save_health(list(health_by_id.values()))
            self.store.save_runs(stored_runs)
            try:
                from notifications import NotificationEngine, NotificationStore
                fresh = [item for item in listings if item.listing_id not in existing_listing_ids]
                NotificationEngine(NotificationStore(self.store.directory)).evaluate_radar(
                    final, fresh, watches, previous_health,
                    list(health_by_id.values()), dry_run=False,
                )
            except Exception as exc:
                notification_error = self._error(
                    run_id, "", "notification", type(exc).__name__,
                    "notification evaluation failed", now, True,
                )
                self.store.save_errors(self.store.load_errors() + [notification_error])
        return PipelineResult(
            final, listings, current_errors, list(health_by_id.values()),
            recognized_count, relevant_count, ignored_unmatched_count,
            needs_review_count,
        )

    def _connector(self, source, watches=()):
        adapter = self.registry.adapter(source.source_type.value)
        kwargs = {}
        if source.source_type == SourceType.FILE_IMPORT:
            kwargs["import_directory"] = self.import_directory
        elif source.source_type == SourceType.MANUAL_URL:
            kwargs["user_directory"] = self.user_directory
        elif source.source_type == SourceType.EBAY_BROWSE:
            kwargs.update(products=self.products, aliases=self.aliases, watches=watches)
        else:
            kwargs["allow_private_network"] = self.allow_private_network
        return adapter(source, **kwargs)

    def _to_listing(self, run_id, source, value, reference, explicitly_supplied,
                    watches, now, product_categories):
        title = str(value.get("title") or "").strip()
        description = str(value.get("description") or "").strip()
        url = str(value.get("url") or "").strip()
        if not title or not url:
            raise ValueError("title and URL are required")
        recognition = self.matcher.recognize(title, description)
        category = product_categories.get(recognition.product_id)
        analysis = DescriptionAnalyzer(as_of=now.date()).analyze(title, description, category)
        watch_match = any(
            watch.active and (not watch.source_ids or source.source_id in watch.source_ids)
            and ((watch.product_id and watch.product_id == recognition.product_id)
                 or (not watch.product_id and watch.query and watch.query.casefold() in f"{title} {description}".casefold()))
            for watch in watches
        )
        recognized = bool(recognition.product_id and recognition.confidence >= 70 and not recognition.ambiguous)
        explicit = explicitly_supplied and source.source_type in {SourceType.MANUAL_URL, SourceType.FILE_IMPORT}
        safe_title, title_removed = sanitize_text(title)
        safe_description, description_removed = sanitize_text(description)
        warnings = list(analysis.warnings)
        if title_removed or description_removed:
            warnings.append("personal data removed from persisted text")
        detected = _datetime(value.get("detected_at"), now)
        external_id = str(value.get("external_id") or "")
        duplicate_key = (
            f"{source.source_id}:{external_id}" if external_id else
            f"url:{url.casefold()}" if url else
            f"fallback:{source.source_id}:{safe_title.casefold()}:{_float(value.get('price'))}"
        )
        safe_reference = "sha256:" + hashlib.sha256(
            f"{source.source_id}|{external_id}|{url}".encode("utf-8")
        ).hexdigest()
        listing = RadarListing(
            run_id, uuid.uuid4().hex, external_id, source.source_id,
            str(value.get("source_name") or source.name),
            url, safe_title, safe_description, _float(value.get("price")),
            str(value.get("currency") or source.currency),
            str(value.get("source_country") or source.country),
            str(value.get("segment") or source.segment), str(value.get("condition") or ""),
            detected, now, now, recognition.product_id or "", recognition.confidence,
            analysis.confidence, duplicate_key, True, safe_reference,
            analysis.shutter_count, analysis.warranty_until, analysis.invoice_available,
            analysis.original_box_available,
            [defect.__dict__ for defect in analysis.defects], analysis.accessories,
            analysis.seller_claims, analysis.missing_information, warnings,
            str(value.get("marketplace_id") or ""),
            str(value.get("original_condition") or value.get("condition") or ""),
            [str(item) for item in value.get("buying_options", [])] if isinstance(value.get("buying_options", []), list) else [],
            _float(value.get("shipping_cost")), str(value.get("shipping_currency") or ""),
            str(value.get("item_location_country") or value.get("source_country") or ""),
            bool(value.get("market_stats_eligible", True)),
        )
        return listing, watch_match or recognized or explicit, recognition

    @staticmethod
    def _upsert(listings, candidate):
        for index, existing in enumerate(listings):
            if existing.duplicate_key == candidate.duplicate_key:
                listings[index] = replace(candidate, listing_id=existing.listing_id, first_seen_at=existing.first_seen_at)
                return listings, False
        return listings + [candidate], True

    @staticmethod
    def _error(run_id, source_id, stage, error_type, message, now, recoverable):
        safe, _ = sanitize_text(message)
        return RadarError(uuid.uuid4().hex, run_id, source_id, now, stage,
                          error_type, safe[:200], "", recoverable)

    @staticmethod
    def _recover_runs(runs, now):
        recovered = []
        updated = []
        for item in runs:
            if item.status == RunStatus.STARTED:
                item = replace(item, status=RunStatus.FAILED, finished_at=now,
                               message="recovered interrupted run")
                recovered.append(RadarError(uuid.uuid4().hex, item.run_id, "", now,
                                            "recovery", "interrupted_run",
                                            "recovered interrupted run", "", False))
            updated.append(item)
        return updated, recovered


def sanitize_text(value: str):
    cleaned = value
    removed = False
    for pattern in _PRIVATE_PATTERNS:
        cleaned, count = pattern.subn("[removed]", cleaned)
        removed = removed or count > 0
    return cleaned, removed


def _datetime(value, fallback):
    if not value:
        return fallback
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _float(value):
    if value in (None, ""):
        return None
    return float(value)
