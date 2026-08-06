"""Independent connector execution, retries, and health aggregation."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .base import Connector
from .models import (
    ConnectorError,
    ConnectorHealth,
    ConnectorStatus,
    Listing,
    ManagerResult,
    ProductSearchResult,
    SearchQuery,
)
from .persistence import OperationalStore


class ConnectorManager:
    def __init__(
        self,
        connectors: Sequence[Connector],
        data_directory: Path,
        sleep_func: Callable[[float], None] = time.sleep,
        monotonic_func: Callable[[], float] = time.monotonic,
        now_func: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.connectors = list(connectors)
        self.store = OperationalStore(data_directory)
        self.sleep_func = sleep_func
        self.monotonic_func = monotonic_func
        self.now_func = now_func

    def search(self, query: SearchQuery) -> ManagerResult:
        all_listings: List[Listing] = []
        connector_results: List[ProductSearchResult] = []
        for connector in self.connectors:
            result = self._run_connector(connector, query)
            connector_results.append(result)
            all_listings.extend(result.listings)
        return ManagerResult(all_listings, connector_results)

    def _run_connector(
        self, connector: Connector, query: SearchQuery
    ) -> ProductSearchResult:
        checked_at = self.now_func()
        previous = self.store.latest_health(connector.name)
        previous_success = self._parse_datetime(
            previous.get("last_success_at", "") if previous else ""
        )
        previous_failures = int(previous.get("consecutive_failures", 0)) if previous else 0

        if not connector.enabled:
            health = ConnectorHealth(
                connector.name,
                connector.source_type,
                ConnectorStatus.DISABLED,
                checked_at,
                previous_success,
                0,
                0,
                previous_failures,
                "Connector is disabled.",
            )
            self.store.append_health(health)
            return ProductSearchResult(connector.name, [], health, 0)

        started = self.monotonic_func()
        listings: List[Listing] = []
        problem: Optional[ConnectorError] = None
        retry_attempted = False
        attempts = connector.retry_count + 1
        for attempt in range(attempts):
            try:
                response = connector.search(query)
                listings, incomplete_count = self._validate_response(
                    connector, response
                )
                problem = None
                if incomplete_count:
                    problem = ConnectorError(
                        "partial_data",
                        f"{incomplete_count} listing(s) contain incomplete optional data.",
                        severity="warning",
                        proposed_action="Review source field mapping and optional values.",
                    )
                break
            except (TimeoutError, ConnectionError) as error:
                error_type = "timeout" if isinstance(error, TimeoutError) else "network"
                problem = ConnectorError(
                    error_type,
                    str(error),
                    transient=True,
                    proposed_action="Check source availability, timeout, and network settings.",
                )
                if attempt < connector.retry_count:
                    retry_attempted = True
                    self.sleep_func(float(2 ** attempt))
                    continue
                listings = []
                break
            except ConnectorError as error:
                problem = error
                if error.transient and error.error_type in {"timeout", "network"} and attempt < connector.retry_count:
                    retry_attempted = True
                    self.sleep_func(float(2 ** attempt))
                    continue
                listings = []
                break
            except Exception as error:
                problem = ConnectorError(
                    "unexpected",
                    f"{type(error).__name__}: {error}",
                    proposed_action="Inspect connector logs and reproduce the exception.",
                )
                listings = []
                break

        duration_ms = max(0, round((self.monotonic_func() - started) * 1000))
        hard_failure = problem is not None and problem.severity != "warning" and not listings

        if hard_failure:
            status = ConnectorStatus.FAILED
            consecutive_failures = previous_failures + 1
            last_success_at = previous_success
            message = problem.message
        else:
            last_success_at = checked_at
            consecutive_failures = 0
            status = ConnectorStatus.DEGRADED if problem else ConnectorStatus.HEALTHY
            message = problem.message if problem else "Connector returned a valid response."
            previously_had_results = bool(previous and int(previous.get("result_count", 0)) > 0)
            if not listings and previously_had_results:
                status = ConnectorStatus.DEGRADED
                problem = ConnectorError(
                    "empty_results",
                    "Connector returned no results after previously returning listings.",
                    severity="warning",
                    proposed_action="Check the query and source availability.",
                )
                message = problem.message
            elif duration_ms > connector.timeout_seconds * 800:
                status = ConnectorStatus.DEGRADED
                problem = ConnectorError(
                    "slow_response",
                    f"Connector response was unusually slow ({duration_ms} ms).",
                    severity="warning",
                    proposed_action="Review latency and connector timeout settings.",
                )
                message = problem.message

        health = ConnectorHealth(
            connector.name,
            connector.source_type,
            status,
            checked_at,
            last_success_at,
            duration_ms,
            len(listings),
            consecutive_failures,
            message,
        )
        self.store.append_health(health)

        incident_count = 0
        if status in {ConnectorStatus.DEGRADED, ConnectorStatus.FAILED} and problem:
            incident, _ = self.store.record_problem(
                connector.name, problem, retry_attempted
            )
            incident_count = 1
            if status == ConnectorStatus.FAILED:
                self.store.write_repair_proposal(connector.name, incident, problem)
        elif status == ConnectorStatus.HEALTHY:
            self.store.resolve_problems(connector.name, checked_at)

        return ProductSearchResult(connector.name, listings, health, incident_count)

    @staticmethod
    def _validate_response(
        connector: Connector, response
    ) -> Tuple[List[Listing], int]:
        if not isinstance(response, list):
            raise ConnectorError(
                "malformed_data",
                "Connector response must be a list of Listing objects.",
                proposed_action="Review the connector response mapping.",
            )
        unique: Dict[str, Listing] = {}
        incomplete = 0
        for index, listing in enumerate(response, start=1):
            if not isinstance(listing, Listing):
                raise ConnectorError(
                    "malformed_data",
                    f"Result {index} is not a normalized Listing.",
                    proposed_action="Review the connector response mapping.",
                )
            required = {
                "external_id": listing.external_id,
                "source": listing.source,
                "title": listing.title,
                "url": listing.url,
                "currency": listing.currency,
                "connector_name": listing.connector_name,
            }
            missing = [field for field, value in required.items() if not value]
            if missing or not isinstance(listing.raw_data, dict):
                field = missing[0] if missing else "raw_data"
                raise ConnectorError(
                    "malformed_data",
                    f"Result {index} has invalid required field {field!r}.",
                    proposed_action="Review required listing field mappings.",
                )
            if listing.connector_name.casefold() != connector.name.casefold():
                raise ConnectorError(
                    "malformed_data",
                    f"Result {index} has the wrong connector_name.",
                    proposed_action="Set connector_name during listing normalization.",
                )
            if listing.price is None or not all(
                (listing.condition, listing.location, listing.seller, listing.description)
            ):
                incomplete += 1
            key = listing.external_id.casefold()
            if key not in unique:
                unique[key] = listing
        return list(unique.values()), incomplete

    @staticmethod
    def _parse_datetime(value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
